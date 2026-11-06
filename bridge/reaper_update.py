# SPDX-License-Identifier: GPL-3.0-or-later
"""Mise à jour du moteur audio (REAPER) — Settings ▸ About.

Philosophie « firmware de modeler » : le rack n'installe JAMAIS « latest » depuis reaper.fm.
La version cible est le PIN de provision/install-reaper.sh (REAPER_VERSION), donc chaque
release GoleM embarque la version Reaper avec laquelle elle a été validée sur la machine de
dev. Le flux utilisateur : update GoleM (carte git au-dessus) -> la carte moteur propose le
nouveau pin -> un tap déclenche la séquence complète, vérifiée et réversible.

DEUX CHEMINS, ET ILS NE PROMETTENT PAS LA MÊME CHOSE (2026-09-22 : « je veux pouvoir
l'installer sans passer par toi ; l'utilisateur final doit pouvoir le faire seul ») :

  1. LE PIN — la version validée avec cette release GoleM. Tarball vérifié contre REAPER_SHA256,
     quelqu'un a JOUÉ dessus avant de l'épingler. C'est le bouton principal, et le défaut.
  2. LA VERSION PUBLIÉE — la dernière que Cockos annonce (`upstream_*`, lue sur reaper.fm au plus une
     fois par jour, en fond ; sans elle, installée 7.79 + pin 7.79 disait « à jour » pendant que la
     7.80 existait). Installable par l'utilisateur, en deux taps, mais SANS les deux garanties :
     Cockos ne publie aucune empreinte (vérifié le 2026-09-22), donc le téléchargement n'est protégé
     que par HTTPS — le rack CALCULE et JOURNALISE le sha256 obtenu, il ne le vérifie contre rien —
     et personne n'a joué cette version sur ce rig. L'écran le dit en toutes lettres avant le geste.

Ce qui protège quand même : l'install est côte à côte, la version précédente RESTE sur le rack, le
smoke test (moteur + lien OSC) fait revenir l'ancienne tout seul en cas d'échec, et la carte offre un
retour en un tap tant que la précédente est là. Une version installée hors pin se voit (`unvalidated`).

Séquence (thread, l'UI poll GET /api/system/reaper-update) :
  download -> install côte à côte (~/opt/reaper-versions/<ver>/REAPER) -> stop audio ->
  bascule du symlink ~/opt/REAPER (atomique) -> restart via provision/start.sh ->
  verify (reaper_running PUIS reaper_connected = OSC vivant, i.e. le Set + golem_watch
  ont chargé sur le nouveau binaire) -> en échec : ROLLBACK auto du symlink + restart.

Layout disque :
  ~/opt/REAPER                     symlink -> version active (start.sh le suit tel quel)
  ~/opt/reaper-versions/<ver>/REAPER   installs côte à côte (rollback instantané)
Première update : l'install historique (~/opt/REAPER répertoire réel) est migrée dans le
layout versionné pendant que Reaper est arrêté. reaper.ini vit dans ~/.config/REAPER,
partagé entre versions — la config/licence survit à la bascule.
"""
import os, re, shutil, subprocess, tempfile, threading, time
import json, sys

from . import config as C
from .state import state
from .golog import swallowed as _swallowed

PREFIX = os.path.expanduser("~/opt")
ACTIVE = os.path.join(PREFIX, "REAPER")                 # ce que start.sh lance (dir OU symlink)
VERSIONS = os.path.join(PREFIX, "reaper-versions")
PIN_FILE = os.path.join(C.ROOT, "provision", "install-reaper.sh")
MIN_FREE_BYTES = 500 * 1024 * 1024                      # marge disque avant download
VERIFY_TIMEOUT = 60                                     # s max pour running+connected après restart

_LOCK = threading.Lock()
_PROG = {"busy": False, "step": None, "log": [], "last": None}   # last = résultat de la dernière update


# ── WINDOWS (2026-10-03) ──────────────────────────────────────────────────────────────────────────
# Tout ce module est le moteur du RACK : une archive Linux posée dans ~/opt, un lien vers la version
# active, start.sh. Sous Windows REAPER vit dans Program Files, posé par son installeur officiel ; la carte
# Licenses ▸ Reaper disait « engine not found » devant un REAPER 7.27 bien installé. Ici : la VRAIE version
# (whatsnew.txt de l'install, comme sur le rack), le pin de provision/windows/pins.json, et la MÊME règle
# de mise à jour (pin, ou version publiée non validée, ancienne gardée à côté, rollback) exécutée par
# bridge/desktop_reaper.py : installeur officiel, une invite UAC, « REAPER (x64).golem-prev » pour le retour.
# L'installeur GoleM, lui, garde un REAPER présent tel quel : changer de moteur est un geste de cet écran.
WINDOWS = sys.platform == "win32"
# ── macOS (2026-10-04, docs/platforms.md M3) ──────────────────────────────────────────────
# REAPER vit dans /Applications/REAPER.app (ou REAPER_BIN). La carte disait « engine not found » : ce
# module ne connaissait que ~/opt. Ici : la VRAIE version (CFBundleShortVersionString de l'Info.plist,
# lue sans lancer l'app) et le pin de provision/macos/pins.json. La mise à jour et le retour arrière ne
# sont PAS écrits pour macOS (lot M3b) : la carte le dit (`can_update`), aucun bouton ne ment.
MACOS = sys.platform == "darwin"
MAC_UNSUPPORTED = "Updating REAPER from golem is not available on macOS yet — install it from reaper.fm"


def _win_pin():
    try:
        with open(os.path.join(C.ROOT, "provision", "windows", "pins.json"), encoding="utf-8") as f:
            return json.load(f)["reaper"]
    except Exception:
        return {}


# ── lecture des versions ─────────────────────────────────────────────────────


def _win_reaper_dir():
    from provision.desktop import reaper_binary
    return os.path.dirname(str(reaper_binary()))


def _mac_app():
    """Le bundle REAPER.app qui contient le binaire lancé par GoleM."""
    from provision.desktop import reaper_binary
    b = reaper_binary()
    app = next((p for p in b.parents if p.suffix == ".app"), None)
    return str(app or b.parent)


def _mac_pin():
    try:
        with open(os.path.join(C.ROOT, "provision", "macos", "pins.json"), encoding="utf-8") as f:
            return json.load(f)["reaper"]
    except Exception:
        return {}


def mac_bundle_version(app):
    """« 7.79 » depuis REAPER.app/Contents/Info.plist (plistlib : binaire ou XML), sans lancer l'app."""
    import plistlib
    try:
        with open(os.path.join(app, "Contents", "Info.plist"), "rb") as f:
            v = str(plistlib.load(f).get("CFBundleShortVersionString") or "")
    except Exception:
        return None
    m = re.match(r"(\d+(?:\.\d+){1,2})", v.strip())
    return m.group(1) if m else None


def _engine_dir():
    return _win_reaper_dir() if WINDOWS else _mac_app() if MACOS else ACTIVE


def pinned_version():
    """Version validée avec la release GoleM installée = défaut REAPER_VERSION du provisioning."""
    if WINDOWS:
        return _win_pin().get("version")
    if MACOS:
        return _mac_pin().get("version")
    try:
        m = re.search(r'REAPER_VERSION:-([\d.]+)', open(PIN_FILE).read())
        return m.group(1) if m else None
    except Exception:
        return None


def pinned_sha256():
    """SHA-256 du tarball épinglé (même fichier que le pin de version — les deux bumpent
    ensemble). None si absent : on ne casse pas une release d'avant le pin."""
    try:
        m = re.search(r'REAPER_SHA256:-([0-9a-f]{64})', open(PIN_FILE).read())
        return m.group(1) if m else None
    except Exception:
        return None


def installed_version(path=None):
    """Version d'une install : 1re ligne de whatsnew.txt (« v7.75 - June 23 2026 »), sans
    lancer le binaire (un `reaper -version` ouvrirait une 2e instance). Fallback : nom du
    répertoire versionné pointé par le symlink."""
    path = path or _engine_dir()
    if MACOS:
        return mac_bundle_version(path)
    try:
        m = re.match(r"v([\d.]+)", open(os.path.join(path, "whatsnew.txt"), encoding="utf-8",
                                        errors="replace").readline().strip())
        if m:
            return m.group(1)
    except Exception as _e:
        _swallowed(_e)
    try:
        m = re.search(r"reaper-versions/([\d.]+)/", os.path.realpath(path) + "/")
        return m.group(1) if m else None
    except Exception:
        return None


# ── la version PUBLIÉE en amont (2026-09-22 : « le golem ne détecte pas la 7.80 ») ────────
# Le rack n'installe JAMAIS « latest » (en-tête) — mais ne rien REGARDER voulait dire ne rien pouvoir
# DIRE : installée 7.79, pin 7.79, donc « à jour », pendant que Cockos publiait la 7.80. Lire n'est pas
# installer : cette valeur n'arme aucun bouton, elle affiche une ligne. Le passage à une version amont
# reste un geste de dev (bumper REAPER_VERSION + REAPER_SHA256 après validation).
#
# Source : la PREMIÈRE ligne de whatsnew.txt de reaper.fm — « v7.80 - September 13 2026 », le même
# format et le même analyseur que le whatsnew.txt d'une install (installed_version).
# ⚠ Jamais dans le battement ni au démarrage : la requête ne part que quand quelqu'un REGARDE la carte
# (status()), au plus une fois par jour, dans un thread — un rack sur scène n'appelle pas reaper.fm, et
# une carte ne doit pas attendre un serveur distant pour s'afficher. Hors ligne = silence, pas d'erreur.
UPSTREAM_URL = "https://www.reaper.fm/whatsnew.txt"
UPSTREAM_TTL = 24 * 3600
UPSTREAM_TIMEOUT = 6
_UP = {"version": None, "at": 0, "error": None, "checking": False}


def _fetch_upstream():
    """La 1re ligne de whatsnew.txt -> « 7.80 ». Lève en cas de panne réseau (l'appelant range)."""
    import urllib.request
    req = urllib.request.Request(UPSTREAM_URL, headers={"User-Agent": "golem-rack (version check)"})
    with urllib.request.urlopen(req, timeout=UPSTREAM_TIMEOUT) as r:
        line = r.readline(200).decode("utf8", "replace").strip()
    m = re.match(r"v([\d.]+)", line)
    if not m:
        raise ValueError(f"première ligne inattendue : {line[:60]!r}")
    return m.group(1)


def _upstream_refresh():
    try:
        v = _fetch_upstream()
        _UP.update(version=v, at=time.time(), error=None)
    except Exception as e:
        # une panne réseau n'efface pas ce qu'on savait : on garde la dernière version vue
        _UP.update(at=time.time(), error=str(e)[:120])
    finally:
        _UP["checking"] = False


def upstream_check(force=False):
    """Rafraîchit la version amont EN FOND si elle est périmée. Ne bloque jamais l'appelant."""
    if _UP["checking"]:
        return
    if not force and _UP["at"] and (time.time() - _UP["at"]) < UPSTREAM_TTL:
        return
    _UP["checking"] = True
    t = threading.Thread(target=_upstream_refresh, daemon=True)
    t.start()
    return t


VER_RE = re.compile(r"^\d+(?:\.\d+){1,2}$")


def installed_versions():
    """Les installs présentes côte à côte : [{version, active}] — ce qui rend un retour possible
    SANS réseau. L'active est celle que pointe le symlink."""
    out = []
    cur = installed_version()
    if MACOS:                                          # une seule install, celle de /Applications
        return [{"version": cur, "active": True}] if cur else []
    if WINDOWS:                                        # Program Files + la précédente gardée à côté
        from . import desktop_reaper
        prev = desktop_reaper.previous_version()
        out = ([{"version": cur, "active": True}] if cur else []) + \
              ([{"version": prev, "active": False}] if prev and prev != cur else [])
        return sorted(out, key=lambda v: _vtuple(v["version"]), reverse=True)
    try:
        names = sorted(os.listdir(VERSIONS))
    except OSError:
        names = []
    for n in names:
        if os.path.isfile(os.path.join(VERSIONS, n, "REAPER", "reaper")):
            out.append({"version": n, "active": n == cur})
    if cur and not any(v["version"] == cur for v in out):
        out.append({"version": cur, "active": True})       # install historique, pas encore versionnée
    return sorted(out, key=lambda v: _vtuple(v["version"]), reverse=True)


def _vtuple(v):
    try:
        return tuple(int(p) for p in v.split("."))
    except Exception:
        return ()


def status(check=True):
    """État pour l'UI : versions + statut + progression de l'update en cours (poll pendant busy).

    `check` : lance au besoin la lecture de la version amont, en fond (jamais bloquante). La valeur
    rendue est celle qu'on CONNAÎT — la première ouverture de la carte peut donc l'apprendre une
    seconde plus tard, et l'écran la relit (`upstream_checking`)."""
    if check and not _PROG["busy"]:
        upstream_check()
    inst, pin = installed_version(), pinned_version()
    if _PROG["busy"]:
        st = "busy"
    elif not inst or not os.path.exists(_engine_dir()):
        st = "not-installed"
    elif not pin:
        st = "no-pin"
    elif _vtuple(inst) < _vtuple(pin):
        st = "update-available"
    elif _vtuple(inst) > _vtuple(pin):
        st = "ahead"
    else:
        st = "up-to-date"
    up = _UP["version"]
    vers = installed_versions()
    return {"installed": inst, "pinned": pin, "status": st,
            # ce qui est SUR LE RACK (retour en un tap) et si le moteur qui tourne a été validé ici
            "versions": vers, "unvalidated": bool(inst and pin and _vtuple(inst) > _vtuple(pin)),
            "busy": _PROG["busy"], "step": _PROG["step"], "log": list(_PROG["log"]),
            "last": _PROG["last"],
            # la version PUBLIÉE par Cockos : une INFORMATION, jamais une cible (aucun bouton)
            "upstream": up, "upstream_at": _UP["at"] or None, "upstream_error": _UP["error"],
            "upstream_checking": _UP["checking"],
            "upstream_newer": bool(up and pin and _vtuple(up) > _vtuple(pin)),
            # Windows : chaque geste passe par une invite UAC sur l'écran du PC — l'écran le dit
            "needs_permission": WINDOWS,
            # macOS : ni mise à jour ni retour arrière depuis GoleM (M3b) — l'écran n'offre pas le geste
            "can_update": not MACOS, "update_unavailable_why": MAC_UNSUPPORTED if MACOS else None}


# ── worker ───────────────────────────────────────────────────────────────────
def _log(line):
    _PROG["log"].append(line)


def _step(name, line):
    _PROG["step"] = name
    _log(line)


def _run(cmd, timeout, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    if r.returncode != 0:
        tail = ((r.stderr or r.stdout) or "").strip().splitlines()
        raise RuntimeError(f"{os.path.basename(cmd[0])}: " + (tail[-1] if tail else f"exit {r.returncode}"))
    return r


def _wait_reaper_dead(timeout=12.0):
    # copie locale de routes_system._wait_reaper_dead (pas d'import croisé bridge->routes)
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if subprocess.run(["pgrep", "-x", "reaper"], capture_output=True, timeout=3).returncode != 0:
                return True
        except Exception as _e:
            _swallowed(_e)
        time.sleep(0.3)
    return False


def _stop_reaper():
    # Reaper repart sur un projet rechargé -> le rig matérialisé n'est plus garanti : on
    # invalide le cache de forme pour forcer un REBUILD à la prochaine émission (cf.
    # routes_system._restart_reaper_async, mêmes raisons).
    with __import__("contextlib").suppress(Exception):
        from . import recall
        recall.invalidate_shape()
    with __import__("contextlib").suppress(Exception):   # lot 8 : une mise à jour n'est pas un abort
        from . import diag
        diag.intent("reaper", "update")
    subprocess.run(["pkill", "-x", "reaper"], timeout=5)
    if not _wait_reaper_dead():
        raise RuntimeError("audio engine would not stop (process still alive)")


def _start_reaper():
    subprocess.Popen(["bash", os.path.join(C.ROOT, "provision", "start.sh")],
                     start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _verify_alive(timeout=VERIFY_TIMEOUT):
    """Smoke test : le nouveau binaire boote, charge le Set et le lien OSC revit
    (reaper_connected = golem_watch émet -> scripts + projet OK, pas juste un process)."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if state.reaper_running and state.reaper_connected:
            return True
        time.sleep(1)
    return False


def _download_and_install(ver, validated=True):
    """Télécharge le tarball officiel (même URL que le provisioning) et installe en
    côte à côte sous VERSIONS/<ver>/REAPER. Ne touche PAS à l'install active.

    `validated=False` (l'utilisateur installe une version publiée que cette release n'a pas
    épinglée) : il n'existe AUCUNE empreinte à laquelle se fier — Cockos n'en publie pas. On ne
    prétend donc pas vérifier : on calcule le sha256 obtenu et on l'ÉCRIT dans le journal, pour
    qu'il soit lisible (et épinglable plus tard si la version s'avère bonne)."""
    dest = os.path.join(VERSIONS, ver)
    if os.path.isfile(os.path.join(dest, "REAPER", "reaper")):
        _log(f"✓ {ver} already downloaded — reusing")
        return dest
    free = shutil.disk_usage(PREFIX).free
    if free < MIN_FREE_BYTES:
        raise RuntimeError(f"not enough disk space ({free // 1024 // 1024} MB free)")
    major = ver.split(".")[0]
    url = f"https://www.reaper.fm/files/{major}.x/reaper{ver.replace('.', '')}_linux_x86_64.tar.xz"
    tmp = tempfile.mkdtemp(prefix="reaper-dl-", dir=PREFIX)
    try:
        _run(["curl", "-fsSL", url, "-o", os.path.join(tmp, "reaper.tar.xz")], timeout=300)
        _log("✓ downloaded " + url.rsplit("/", 1)[-1])
        # intégrité (audit 2026-08-12, M-3) : un tarball qui s'installe se VÉRIFIE. Le hash
        # vit à côté du pin de version — pas de hash connu (vieille release) = on le dit.
        want = pinned_sha256() if validated else None
        if want:
            import hashlib
            h = hashlib.sha256()
            with open(os.path.join(tmp, "reaper.tar.xz"), "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            if h.hexdigest() != want:
                raise RuntimeError(f"tarball sha256 mismatch (got {h.hexdigest()[:12]}…, "
                                   f"pinned {want[:12]}…) — refusing to install")
            _log("✓ sha256 verified against the pinned release")
        elif validated:
            # audit 2026-10-15 : la version VALIDÉE porte toujours son empreinte (provision/install-reaper.sh) — si elle
            # manque, quelque chose ne va pas ; on n'installe pas un binaire qu'on prétend vérifié sans l'avoir vérifié
            raise RuntimeError("no pinned sha256 for the validated release — refusing to install unverified")
        else:
            import hashlib
            h = hashlib.sha256()
            with open(os.path.join(tmp, "reaper.tar.xz"), "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            _log(f"⚠ version not validated for this release — nothing to verify against "
                 f"(Cockos publishes no checksum). Downloaded sha256: {h.hexdigest()}")
        _step("install", f"⏳ installing {ver} (side by side)…")
        _run(["tar", "-xf", os.path.join(tmp, "reaper.tar.xz"), "-C", tmp], timeout=120)
        os.makedirs(dest, exist_ok=True)
        # installeur officiel : --install <dir> place dans <dir>/REAPER (pas d'intégration
        # desktop pour les installs versionnées — seule l'active a son entrée de menu)
        _run([os.path.join(tmp, "reaper_linux_x86_64", "install-reaper.sh"), "--install", dest],
             timeout=120)
        if not os.path.isfile(os.path.join(dest, "REAPER", "reaper")):
            raise RuntimeError("install produced no reaper binary")
        _log(f"✓ installed to reaper-versions/{ver}")
        return dest
    except Exception:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _receipt_layout():
    """Reçu d'install (docs/uninstall.md §2) : ~/opt/REAPER devient un LIEN et ~/opt/reaper-versions naît — c'est
    REAPER (groupe `reaper`, offert à la désinstallation seulement si golem l'a installé). Jamais d'exception."""
    try:
        from . import install_receipt
        if os.path.isdir(VERSIONS):
            install_receipt.add(VERSIONS, "dir", "reaper", by="bridge/reaper_update.py")
        if os.path.islink(ACTIVE):
            install_receipt.add(ACTIVE, "link", "reaper", by="bridge/reaper_update.py")
    except Exception as e:
        _swallowed(e, "reaper_update._receipt_layout")


def _point_active_to(ver):
    """Bascule atomique du symlink ACTIVE vers VERSIONS/<ver>/REAPER."""
    target = os.path.join(VERSIONS, ver, "REAPER")
    tmp = ACTIVE + ".switch"
    with __import__("contextlib").suppress(FileNotFoundError):
        os.remove(tmp)
    os.symlink(target, tmp)
    os.replace(tmp, ACTIVE)


def _migrate_legacy_install(old_ver):
    """Install historique = répertoire réel ~/opt/REAPER -> la ranger dans le layout versionné.
    Appelé Reaper arrêté uniquement. No-op si ACTIVE est déjà un symlink."""
    if os.path.islink(ACTIVE) or not os.path.isdir(ACTIVE):
        return
    slot = os.path.join(VERSIONS, old_ver or "unknown")
    os.makedirs(slot, exist_ok=True)
    os.rename(ACTIVE, os.path.join(slot, "REAPER"))
    _point_active_to(old_ver or "unknown")
    _receipt_layout()
    _log(f"✓ migrated existing install to reaper-versions/{old_ver}")


def _prune_versions(keep):
    """Garde uniquement les versions utiles (nouvelle + précédente = rollback), vire le reste."""
    try:
        for name in os.listdir(VERSIONS):
            if name not in keep:
                shutil.rmtree(os.path.join(VERSIONS, name), ignore_errors=True)
    except FileNotFoundError:
        pass


def _worker(old_ver, new_ver, validated=True):
    try:
        _step("download", f"⏳ downloading REAPER {new_ver}…")
        os.makedirs(VERSIONS, exist_ok=True)
        _download_and_install(new_ver, validated=validated)

        _step("stop", "⏳ stopping audio engine…")
        _stop_reaper()
        _log("✓ audio engine stopped")

        _step("switch", f"⏳ switching engine to {new_ver}…")
        _migrate_legacy_install(old_ver)
        _point_active_to(new_ver)
        _receipt_layout()
        _log(f"✓ active engine -> {new_ver}")

        _step("restart", "⏳ restarting audio engine…")
        _start_reaper()

        _step("verify", "⏳ verifying (engine boots + rig link alive)…")
        if _verify_alive():
            _log(f"✓ engine {new_ver} is up — set loaded, OSC link alive")
            _prune_versions({old_ver, new_ver, pinned_version()})   # l'ancienne RESTE : retour en un tap
            _PROG["last"] = {"ok": True, "from": old_ver, "to": new_ver, "rolled_back": False,
                             "validated": validated}
            return

        # échec du smoke test -> ROLLBACK automatique sur l'ancienne version
        _step("rollback", f"✗ engine {new_ver} did not come back — rolling back to {old_ver}…")
        _stop_reaper()
        _point_active_to(old_ver)
        _start_reaper()
        recovered = _verify_alive()
        _log("✓ rolled back — previous engine is up" if recovered
             else "⚠ rollback done but engine still not verified — check the Dashboard")
        _PROG["last"] = {"ok": False, "from": old_ver, "to": new_ver, "rolled_back": True, "validated": validated,
                         "error": f"engine {new_ver} failed verification — rolled back to {old_ver}"}
    except Exception as e:
        _log(f"✗ {e}")
        _PROG["last"] = {"ok": False, "from": old_ver, "to": new_ver, "rolled_back": False,
                         "validated": validated, "error": str(e)}
        # le moteur a pu être arrêté avant l'échec -> best-effort : le relancer tel quel
        if not state.reaper_running:
            with __import__("contextlib").suppress(Exception):
                _start_reaper()
    finally:
        _PROG["busy"], _PROG["step"] = False, None


def start_update(version=None):
    """Lance l'update moteur (thread). `version` = une cible explicite ; par défaut, le PIN.

    Une cible autre que le pin n'est acceptée que si c'est la version PUBLIÉE que le rack a lue chez
    Cockos : on n'installe pas une chaîne arrivée d'un écran (« 9.99 », « ../etc »). Elle part alors
    en mode NON VALIDÉ (pas d'empreinte à vérifier, personne n'a joué dessus) — l'écran l'a dit avant.
    Retourne (ok, erreur)."""
    if MACOS:
        return False, MAC_UNSUPPORTED
    with _LOCK:
        if _PROG["busy"]:
            return False, "an engine update is already running"
        inst, pin = installed_version(), pinned_version()
        if not inst:
            return False, "cannot read the installed engine version"
        target = str(version or "").strip() or pin
        if not target:
            return False, "no pinned engine version in this golem release"
        if not VER_RE.match(target):
            return False, f"not a REAPER version: {target!r}"
        validated = target == pin
        if not validated and target != (_UP["version"] or ""):
            return False, (f"{target} is not the version published by Cockos "
                           f"({_UP['version'] or 'not read yet'}) — refusing to install it")
        if _vtuple(inst) >= _vtuple(target):
            return False, f"engine {inst} is already {'newer than' if _vtuple(inst) > _vtuple(target) else 'at'} {target}"
        _PROG.update(busy=True, step="download", log=[], last=None)
    threading.Thread(target=_win_worker if WINDOWS else _worker, args=(inst, target, validated),
                     daemon=True).start()
    return True, None


def _win_run(job):
    """Enveloppe des workers Windows : même `last`, même relance best-effort qu'au rack."""
    try:
        _PROG["last"] = job()
    except Exception as e:
        _log(f"✗ {e}")
        _PROG["last"] = {"ok": False, "rolled_back": False, "error": str(e)}
    finally:
        _PROG["busy"], _PROG["step"] = False, None


def _win_worker(old_ver, new_ver, validated=True):
    from . import desktop_reaper
    pin = _win_pin()
    _win_run(lambda: desktop_reaper.run_update(old_ver, new_ver, validated, pin.get("url"), pin.get("sha256"),
                                               _step, _log))
    _PROG["last"].setdefault("from", old_ver)
    _PROG["last"].setdefault("to", new_ver)


def _win_switch_worker(old_ver, ver):
    from . import desktop_reaper
    _win_run(lambda: desktop_reaper.run_switch(old_ver, ver, _step, _log))
    _PROG["last"].setdefault("from", old_ver)
    _PROG["last"].setdefault("to", ver)


def _switch_worker(old_ver, ver):
    """Bascule vers une version DÉJÀ installée (retour arrière) : aucun réseau, aucun téléchargement."""
    try:
        _step("stop", "⏳ stopping audio engine…")
        _stop_reaper()
        _step("switch", f"⏳ switching engine to {ver}…")
        _migrate_legacy_install(old_ver)
        _point_active_to(ver)
        _step("restart", "⏳ restarting audio engine…")
        _start_reaper()
        _step("verify", "⏳ verifying (engine boots + rig link alive)…")
        if _verify_alive():
            _log(f"✓ engine {ver} is up — set loaded, OSC link alive")
            _PROG["last"] = {"ok": True, "from": old_ver, "to": ver, "rolled_back": False, "switch": True}
            return
        _step("rollback", f"✗ engine {ver} did not come back — rolling back to {old_ver}…")
        _stop_reaper()
        _point_active_to(old_ver)
        _start_reaper()
        _verify_alive()
        _PROG["last"] = {"ok": False, "from": old_ver, "to": ver, "rolled_back": True, "switch": True,
                         "error": f"engine {ver} failed verification — rolled back to {old_ver}"}
    except Exception as e:
        _log(f"✗ {e}")
        _PROG["last"] = {"ok": False, "from": old_ver, "to": ver, "rolled_back": False, "switch": True,
                         "error": str(e)}
        if not state.reaper_running:
            with __import__("contextlib").suppress(Exception):
                _start_reaper()
    finally:
        _PROG["busy"], _PROG["step"] = False, None


def start_switch(version):
    """Revient à une version DÉJÀ sur le rack (« Use 7.79 ») — le filet de l'install non validée :
    elle ne dépend ni du réseau ni de reaper.fm, seulement de ce qui est sur le disque."""
    if MACOS:
        return False, MAC_UNSUPPORTED
    with _LOCK:
        if _PROG["busy"]:
            return False, "an engine update is already running"
        ver = str(version or "").strip()
        inst = installed_version()
        have = {v["version"] for v in installed_versions()}
        if not VER_RE.match(ver):
            return False, f"not a REAPER version: {ver!r}"
        if ver not in have:
            return False, f"{ver} is not installed on this rack"
        if ver == inst:
            return False, f"engine {ver} is already the one running"
        _PROG.update(busy=True, step="switch", log=[], last=None)
    threading.Thread(target=_win_switch_worker if WINDOWS else _switch_worker, args=(inst, ver),
                     daemon=True).start()
    return True, None
