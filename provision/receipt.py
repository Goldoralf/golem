#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Le REÇU D'INSTALLATION (docs/uninstall.md §2, §9.2) : ce que l'install a créé, et l'état de la machine AVANT elle.

    Linux    ~/.local/share/golem/install-receipt.json                (de l'utilisateur qui installe — sous sudo : $SUDO_USER)
    Windows  %LOCALAPPDATA%\\GoleM\\install-receipt.json             (pas de sudo : l'utilisateur qui lance l'installateur)
    macOS    ~/Library/Application Support/golem/install-receipt.json

Bibliothèque standard seulement (Python 3.10+) : appelé par les scripts de provision/ AVANT que le venv existe,
et par le bridge à l'exécution. Ligne de commande :

    receipt.py add PATH --kind file|dir|link --by SCRIPT --group G [--owner user|root] [--moved-to ORIG] [--existed]
    receipt.py prior KEY VALUE [--string]        clé pointée (reaper_ini.keys.automute) ; VALUE en JSON ou texte
    receipt.py prior KEY --file PATH             la valeur = le contenu du fichier, null s'il n'existe pas
    receipt.py prior-ufw                         lit `ufw status` sur stdin -> prior.ufw {active, rules}
    receipt.py get KEY                           imprime la valeur prior (JSON) ; code 1 si absente
    receipt.py apt-snapshot before|after         paquets installés avant / différence après -> apt.added
    receipt.py deb NAME                          un .deb posé par dpkg -i -> apt.debs
    receipt.py apt-requested PKG…                les paquets qu'un script DEMANDE à apt-get install / dpkg -i
                                                 -> apt.requested (les explicites ; le reste de apt.added = dépendances)
    receipt.py set-root DIR [--release TAG]
    receipt.py merge-pending [--create]          verse les FRAGMENTS en attente (<reçu>.pending-*.json, §9.2)
    receipt.py show

Règles (le contrat, §2) :
  · l'état antérieur s'écrit UNE fois : un `prior` déjà présent n'est JAMAIS remplacé — le premier est la
    machine d'avant golem (c'est ce qui remplace les .bak qui s'écrasent eux-mêmes) ;
  · les éléments sont dédoublonnés par id (« kind:chemin ») ; une fusion ne remplace jamais leur `prior` ;
  · écriture atomique (tmp + os.replace) sous verrou (fcntl ; msvcrt sous Windows) : plusieurs scripts écrivent ;
  · sous sudo, le fichier (et les dossiers qu'on crée) est rendu à l'utilisateur (Linux/macOS seulement) ;
  · les chemins du home s'écrivent avec `~` (Linux, macOS) ; sous Windows, les chemins d'un élément s'écrivent
    relatifs à %LOCALAPPDATA%, %APPDATA% ou %USERPROFILE% (le plus long gagne) — un chemin système (Program Files,
    ProgramData) reste absolu. `expand()` rend le chemin réel, sur chaque OS : un lecteur passe TOUJOURS par lui ;
  · FRAGMENTS (§9.2) : ce qui ne peut pas appeler ce helper (le bootstrap PowerShell, avant que le dépôt existe ;
    le script élevé, qui tourne en administrateur) dépose `<reçu>.pending-<nom>.json` à côté du reçu. Le prochain
    passage sous verrou les verse (le premier gagne, comme partout) et les efface.
Un script d'install appelle ce helper avec `|| true` : un reçu raté ne casse JAMAIS une installation.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile

import glob
import ntpath
import time

try:
    import fcntl
except ImportError:                     # Windows : pas de verrou POSIX — msvcrt prend le relais
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None
try:
    import pwd
except ImportError:
    pwd = None

FORMAT = 1
KINDS = ("file", "dir", "link")
REL = os.path.join(".local", "share", "golem", "install-receipt.json")
PENDING = ".pending-"                    # <reçu>.pending-<nom>.json : un fragment à verser (§9.2)
LOCK_WAIT = 30                           # secondes : au-delà, un verrou tenu est une panne, pas une attente


def _os():
    """« win32 », « darwin » ou « linux » — lu à l'appel (les tests simulent un autre OS)."""
    if sys.platform == "win32":
        return "win32"
    return "darwin" if sys.platform == "darwin" else "linux"


# ── à qui appartient le reçu ──────────────────────────────────────────────────────────────────
def _sudo_user():
    """(home, uid, gid) de l'utilisateur qui a lancé sudo — None hors sudo (ou sudo vers soi-même).
    Windows : jamais (pas de sudo ; le script élevé reçoit le chemin du reçu en paramètre)."""
    if _os() == "win32":
        return None
    if pwd is None or not hasattr(os, "geteuid") or os.geteuid() != 0:
        return None
    name = os.environ.get("SUDO_USER") or ""
    if not name or name == "root":
        return None
    try:
        pw = pwd.getpwnam(name)
    except KeyError:
        return None
    return pw.pw_dir, pw.pw_uid, pw.pw_gid


def user_home():
    if _os() == "win32":
        return os.environ.get("USERPROFILE") or os.path.expanduser("~")
    su = _sudo_user()
    return su[0] if su else os.path.expanduser("~")


def _local_appdata():
    return os.environ.get("LOCALAPPDATA") or ntpath.join(user_home(), "AppData", "Local")


def default_path():
    """Le reçu de CET utilisateur, sur CET OS (docs/uninstall.md §2, §9.2)."""
    o = _os()
    if o == "win32":
        return ntpath.join(_local_appdata(), "GoleM", "install-receipt.json")
    if o == "darwin":
        return os.path.join(user_home(), "Library", "Application Support", "golem", "install-receipt.json")
    return os.path.join(user_home(), REL)


def receipt_path():
    # GOLEM_RECEIPT : un autre fichier (tests, VM) — jamais utile en production
    return os.environ.get("GOLEM_RECEIPT") or default_path()


def _give_back(path):
    """Sous sudo : rend le chemin à l'utilisateur (sinon il ne pourrait plus écrire son propre reçu)."""
    su = _sudo_user()
    if su:
        try:
            os.chown(path, su[1], su[2])
        except OSError:
            pass


def _makedirs(d):
    """mkdir -p, en rendant à l'utilisateur chaque dossier qu'on CRÉE (pas ceux qui existaient)."""
    missing = []
    cur = os.path.abspath(d)
    while not os.path.isdir(cur):
        missing.append(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    for p in reversed(missing):
        try:
            os.mkdir(p, 0o755)
        except FileExistsError:
            continue
        _give_back(p)


# Windows : les racines de l'utilisateur, la plus longue d'abord (%LOCALAPPDATA% est DANS %USERPROFILE%)
WIN_VARS = ("LOCALAPPDATA", "APPDATA", "USERPROFILE")


def _win_roots():
    roots = []
    for var in WIN_VARS:
        val = os.environ.get(var)
        if not val and var == "USERPROFILE":
            val = user_home()
        if val:
            roots.append((var, ntpath.normpath(val).rstrip("\\")))
    return sorted(roots, key=lambda r: -len(r[1]))


def win_relative(path):
    """Windows : C:\\Users\\u\\AppData\\Roaming\\REAPER -> %APPDATA%\\REAPER. Un chemin hors du profil reste absolu.
    La casse est ignorée (NTFS) ; la forme rendue garde la casse du chemin donné."""
    p = str(path)
    if p.startswith("%"):
        return p
    p = ntpath.normpath(p)
    low = p.lower()
    for var, root in _win_roots():
        r = root.lower()
        if low == r:
            return f"%{var}%"
        if low.startswith(r + "\\"):
            return f"%{var}%" + p[len(root):]
    return p


def tilde(path, home=None):
    """Chemin absolu, le home en `~` (Windows : %LOCALAPPDATA%, %APPDATA%, %USERPROFILE%). Les liens ne sont PAS
    résolus : on décrit le lien lui-même."""
    if _os() == "win32" and home is None:
        return win_relative(path)
    home = (home or user_home()).rstrip("/")
    p = path
    if p == "~" or p.startswith("~/"):
        return p
    p = os.path.abspath(os.path.expanduser(p))
    if p == home:
        return "~"
    if home and p.startswith(home + "/"):
        return "~" + p[len(home):]
    return p


def expand(path):
    """L'inverse de tilde() : le chemin réel d'un chemin du reçu, sur l'OS qui le lit — `~` (Linux, macOS),
    `%VAR%` (Windows). Un chemin absolu passe tel quel ; une variable inconnue reste telle quelle."""
    if not isinstance(path, str) or not path:
        return path
    if _os() == "win32":
        if path.startswith("%"):
            end = path.find("%", 1)
            if end > 1:
                var = path[1:end]
                val = os.environ.get(var) or os.environ.get(var.upper())
                if not val and var.upper() == "USERPROFILE":
                    val = user_home()
                if not val and var.upper() == "LOCALAPPDATA":
                    val = _local_appdata()
                if val:
                    return ntpath.normpath(val + path[end + 1:])
            return path
        if path == "~" or path.startswith(("~\\", "~/")):
            return ntpath.normpath(user_home() + path[1:])
        return path
    if path == "~" or path.startswith("~/"):
        return user_home() + path[1:]
    return path


def _now():
    return datetime.datetime.now().replace(microsecond=0).isoformat()


def _skeleton():
    t = _now()
    return {"format": FORMAT, "root": None, "created": t, "updated": t, "release": None,
            "items": [], "apt": {"added": [], "debs": []}, "prior": {}}


# ── lecture / écriture sous verrou ────────────────────────────────────────────────────────────
def _lock(fd):
    """Verrou exclusif : flock (POSIX), sinon msvcrt.locking sur le premier octet (Windows). msvcrt n'attend pas
    indéfiniment (LK_LOCK abandonne après 10 s) : on réessaie en non bloquant jusqu'à LOCK_WAIT."""
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    if msvcrt is None:
        return
    deadline = time.monotonic() + LOCK_WAIT
    while True:
        os.lseek(fd, 0, 0)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.05)


def _unlock(fd):
    if fcntl is not None:
        fcntl.flock(fd, fcntl.LOCK_UN)
    elif msvcrt is not None:
        os.lseek(fd, 0, 0)
        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass


class _Locked:
    """Verrou exclusif sur <reçu>.lock pendant lecture-modification-écriture."""

    def __init__(self, path):
        self.path = path
        self.fd = None

    def __enter__(self):
        _makedirs(os.path.dirname(self.path))
        lock = self.path + ".lock"
        fresh = not os.path.exists(lock)
        self.fd = os.open(lock, os.O_RDWR | os.O_CREAT, 0o644)
        if fresh:
            _give_back(lock)
        try:
            _lock(self.fd)
        except BaseException:
            os.close(self.fd)
            raise
        return self

    def __exit__(self, *exc):
        _unlock(self.fd)
        os.close(self.fd)
        return False


def _read(path):
    try:
        # utf-8-sig : un BOM (PowerShell 5.1 en pose un avec -Encoding UTF8) n'est pas une corruption
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        return _skeleton()
    except (OSError, ValueError):
        # un reçu illisible n'est PAS écrasé : il porte peut-être l'état d'avant golem — on le met de côté
        aside = f"{path}.corrupt-{datetime.datetime.now():%Y%m%d-%H%M%S}"
        try:
            os.replace(path, aside)
            print(f"receipt: unreadable receipt moved to {aside}", file=sys.stderr)
        except OSError:
            pass
        return _skeleton()
    if not isinstance(data, dict):
        return _skeleton()
    base = _skeleton()
    for k, v in base.items():
        data.setdefault(k, v)
    if not isinstance(data.get("apt"), dict):
        data["apt"] = {"added": [], "debs": []}
    data["apt"].setdefault("added", [])
    data["apt"].setdefault("debs", [])
    if not isinstance(data.get("prior"), dict):
        data["prior"] = {}
    if not isinstance(data.get("items"), list):
        data["items"] = []
    return data


def _write(path, data):
    data["updated"] = _now()
    d = os.path.dirname(path)
    fd, tmp = tempfile.mkstemp(prefix=".install-receipt-", suffix=".tmp", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o644)
        _give_back(tmp)
        _replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _replace(src, dst):
    """os.replace — sous Windows, un lecteur qui tient le fichier fait échouer le remplacement (PermissionError) :
    on réessaie un court instant au lieu de perdre l'écriture."""
    for i in range(40):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if _os() != "win32" or i == 39:
                raise
            time.sleep(0.05)


def _update(fn):
    """Applique fn(reçu) sous verrou, puis écrit. Rend ce que fn rend. Les fragments en attente sont versés au
    passage (ils précèdent fn : le bootstrap a vu la machine avant tout le reste)."""
    path = receipt_path()
    with _Locked(path):
        data = _read(path)
        before = json.dumps(data, sort_keys=True)
        merged = _merge_pending(data, path)
        out = fn(data)
        # rien de neuf (un `prior` déjà là, un élément déjà connu) : on ne réécrit pas — pas de date qui bouge
        if json.dumps(data, sort_keys=True) != before or not os.path.isfile(path):
            _write(path, data)
        for frag in merged:                     # versés ET écrits : on peut les effacer
            try:
                os.unlink(frag)
            except OSError:
                pass
    return out


def exists():
    return os.path.isfile(receipt_path())


def load():
    """Le reçu tel qu'il est (squelette vide s'il n'existe pas), fragments en attente versés EN MÉMOIRE — sans rien
    écrire ni effacer."""
    path = receipt_path()
    data = None
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8-sig") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = None
    if not isinstance(data, dict):
        data = _skeleton()
    else:
        base = _skeleton()
        for k, v in base.items():
            data.setdefault(k, v)
    try:
        _merge_pending(data, path, keep=True)
    except Exception:
        pass
    return data


# ── les fragments (docs/uninstall.md §9.2) ────────────────────────────────────────────────────
# Un fragment est un petit JSON écrit par ce qui ne peut pas appeler ce helper :
#   {"format": 1, "by": "provision/windows/install-system.ps1",
#    "items":  [{"path": "C:\\ProgramData\\GoleM", "kind": "dir", "group": "system", "owner": "root",
#                "existed": false, "moved_to": null}],
#    "prior":  {"programs.reaper.installed_by_golem": true, "python.version": "3.12.10"},   clés POINTÉES, le 1er gagne
#    "append": {"prior.firewall_deleted": [{"name": "…", …}], "firewall.added": ["GoleM - bridge"]}}
# `append` : des listes qu'on complète (dédoublonnées — par `name` pour un objet) : ce que golem a SUPPRIMÉ ou
# créé à chaque passage compte, pas seulement au premier.
def pending_fragments(path=None):
    path = path or receipt_path()
    return sorted(glob.glob(glob.escape(path) + PENDING + "*.json"))


def _apply_fragment(data, frag):
    by = str(frag.get("by") or "fragment")
    for it in frag.get("items") or []:
        if not isinstance(it, dict) or not it.get("path") or it.get("kind") not in KINDS:
            continue
        _add_into(data, it["path"], it["kind"], str(it.get("by") or by), str(it.get("group") or "golem"),
                  it.get("owner"), it.get("moved_to"), bool(it.get("existed")))
    for key, value in (frag.get("prior") or {}).items():
        _prior_into(data, key, value)
    for key, values in (frag.get("append") or {}).items():
        parts = _split(key)
        node = data
        for k in parts[:-1]:
            if not isinstance(node.get(k), dict):
                node[k] = {}
            node = node[k]
        lst = node.get(parts[-1])
        if not isinstance(lst, list):
            lst = node[parts[-1]] = []
        for v in values if isinstance(values, list) else [values]:
            if isinstance(v, dict) and v.get("name") is not None:
                if any(isinstance(x, dict) and x.get("name") == v["name"] for x in lst):
                    continue
            elif v in lst:
                continue
            lst.append(v)


def _merge_pending(data, path, keep=False):
    """Verse les fragments <reçu>.pending-*.json dans `data`. Rend les fichiers versés (à effacer après l'écriture).
    Un fragment illisible est mis de côté (.bad), jamais effacé : il porte peut-être l'état d'avant golem."""
    done = []
    for frag_path in pending_fragments(path):
        try:
            with open(frag_path, encoding="utf-8-sig") as f:
                frag = json.load(f)
            if not isinstance(frag, dict):
                raise ValueError("not an object")
        except (OSError, ValueError) as e:
            if not keep:
                try:
                    os.replace(frag_path, frag_path + ".bad")
                    print(f"receipt: unreadable fragment {frag_path} set aside ({e})", file=sys.stderr)
                except OSError:
                    pass
            continue
        _apply_fragment(data, frag)
        done.append(frag_path)
    return done


def merge_pending(create=False):
    """Verse les fragments en attente. Sans reçu, rien (sauf `create`) : le bridge n'écrit que dans un reçu qui
    existe. Rend le nombre de fragments versés."""
    n = len(pending_fragments())
    if not n or (not exists() and not create):
        return 0
    _update(lambda data: None)
    return n - len(pending_fragments())


# ── les opérations ────────────────────────────────────────────────────────────────────────────
def _item(path, kind, by, group, owner=None, moved_to=None, existed=False):
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    p = tilde(path)
    if owner is None:
        # « root » : il faut les droits du système pour l'ôter (sous Windows : administrateur)
        owner = "user" if p.startswith(("~", "%")) else "root"
    if owner not in ("user", "root"):
        raise ValueError("owner must be user or root")
    prior = None
    if moved_to:
        prior = {"moved_to": tilde(moved_to)}
    elif existed:
        prior = {"existed": True}
    return {"id": f"{kind}:{p}", "kind": kind, "path": p, "owner": owner, "by": by, "group": group, "prior": prior}


def _add_into(data, path, kind, by, group, owner=None, moved_to=None, existed=False):
    new = _item(path, kind, by, group, owner, moved_to, existed)
    prior = new["prior"]
    for it in data["items"]:
        if isinstance(it, dict) and it.get("id") == new["id"]:
            it.update({"by": by, "group": group, "owner": new["owner"]})
            if it.get("prior") is None and prior and "moved_to" in prior:
                it["prior"] = prior
            return it
    data["items"].append(new)
    return new


def add(path, kind, by, group, owner=None, moved_to=None, existed=False):
    """Un élément créé par l'install. Dédoublonné par id ; une fusion met à jour by/group/owner mais ne
    remplace JAMAIS un `prior` déjà écrit — sauf un `prior` vide qui reçoit un original mis de côté
    (perdre ce chemin, c'est ne jamais rendre son fichier à l'utilisateur)."""
    _item(path, kind, by, group, owner, moved_to, existed)          # valide AVANT de prendre le verrou
    return _update(lambda data: _add_into(data, path, kind, by, group, owner, moved_to, existed))


def _split(key):
    parts = [k for k in str(key).split(".") if k]
    if not parts:
        raise ValueError("empty key")
    return parts


def _prior_into(data, key, value):
    parts = _split(key)
    node = data["prior"]
    for k in parts[:-1]:
        if k not in node:
            node[k] = {}
        node = node[k]
        if not isinstance(node, dict):
            print(f"receipt: prior.{key}: {k} is not an object — left as is", file=sys.stderr)
            return False
    if parts[-1] in node:
        return False                          # le premier gagne : c'était la machine d'avant golem
    node[parts[-1]] = value
    return True


def prior(key, value):
    """Écrit prior.<key> = value SEULEMENT s'il n'existe pas. Rend True si écrit, False si déjà là."""
    _split(key)
    return _update(lambda data: _prior_into(data, key, value))


_MISSING = object()


def get_prior(key, default=None):
    node = load().get("prior") or {}
    for k in _split(key):
        if not isinstance(node, dict) or k not in node:
            return default
        node = node[k]
    return node


def _has_prior(key):
    return get_prior(key, _MISSING) is not _MISSING


def parse_ufw(text):
    """`ufw status` -> {"active": bool, "rules": [lignes]} ; ufw absent ou muet -> inactif, sans règle."""
    active, rules, body = False, [], False
    for line in (text or "").splitlines():
        s = line.strip()
        if s.lower().startswith("status:"):
            active = s.split(":", 1)[1].strip().lower() == "active"
            continue
        if s.startswith("--"):
            body = True
            continue
        if body and s:
            rules.append(s)
    return {"active": active, "rules": rules}


def installed_packages():
    """Paquets réellement INSTALLÉS (pas ceux dont il ne reste que la config)."""
    out = subprocess.run(["dpkg-query", "-W", "-f=${db:Status-Status}\t${Package}\n"],
                         capture_output=True, text=True, check=True).stdout
    return sorted({ln.split("\t", 1)[1] for ln in out.splitlines()
                   if "\t" in ln and ln.split("\t", 1)[0] == "installed"})


def _snapshot_path():
    return receipt_path() + ".apt-before"


def apt_snapshot(phase, packages=None):
    """before : photographie les paquets installés, JUSTE avant un apt/dpkg de l'install (toujours fraîche :
    une photo d'une install précédente attribuerait à golem ce que l'utilisateur a posé depuis).
    after : la différence s'ajoute à apt.added (fusion, dédoublonnée). Un paquet présent dans `before`
    n'est jamais ajouté. Sans photo `before`, `after` ne devine rien. Rend la liste ajoutée."""
    pkgs = list(packages) if packages is not None else installed_packages()
    snap = _snapshot_path()
    if phase == "before":
        with _Locked(receipt_path()):
            _makedirs(os.path.dirname(snap))
            fd, tmp = tempfile.mkstemp(prefix=".apt-before-", dir=os.path.dirname(snap))
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write("\n".join(pkgs) + "\n")
            os.chmod(tmp, 0o644)
            _give_back(tmp)
            os.replace(tmp, snap)
        return []
    if phase != "after":
        raise ValueError("phase must be before or after")
    try:
        with open(snap, encoding="utf-8") as f:
            before = {ln.strip() for ln in f if ln.strip()}
    except FileNotFoundError:
        print("receipt: apt-snapshot after without a 'before' snapshot — nothing recorded", file=sys.stderr)
        return []
    new = sorted(set(pkgs) - before)

    def fn(data):
        added = data["apt"]["added"]
        debs = set(data["apt"]["debs"])
        for p in new:
            if p not in added and p not in debs:
                added.append(p)
        return new
    return _update(fn)


def deb(name):
    def fn(data):
        if name not in data["apt"]["debs"]:
            data["apt"]["debs"].append(name)
        if name in data["apt"]["added"]:          # un .deb n'est pas « un paquet apt » : une seule place
            data["apt"]["added"].remove(name)
    return _update(fn)


def apt_requested(names):
    """Les paquets qu'un script nomme EXPLICITEMENT (apt-get install X Y, dpkg -i X.deb) -> apt.requested, fusion
    dédoublonnée. On note la DEMANDE, pas l'effet : un paquet déjà là avant golem n'est pas dans apt.added, et le
    moteur de désinstallation ne garde que requested ∩ added (docs/uninstall.md §2, §3). Les noms `pkg:arch` sont
    ramenés à `pkg` (dpkg-query écrit apt.added sans architecture) ; un chemin de .deb est ignoré."""
    clean = []
    for n in names:
        n = str(n).strip()
        if not n or n.startswith("-") or "/" in n or n.endswith(".deb"):
            continue
        n = n.split(":", 1)[0].split("=", 1)[0]
        if n and n not in clean:
            clean.append(n)

    def fn(data):
        req = data["apt"].get("requested")
        if not isinstance(req, list):
            req = data["apt"]["requested"] = []
        for n in clean:
            if n not in req:
                req.append(n)
        return clean
    return _update(fn)


def set_root(d, release=None):
    root = os.path.abspath(os.path.expanduser(d))

    def fn(data):
        if data.get("root") and data["root"] != root:
            print(f"receipt: root was {data['root']}, now {root}", file=sys.stderr)
        data["root"] = root
        if release:
            data["release"] = release
    return _update(fn)


# ── ligne de commande ─────────────────────────────────────────────────────────────────────────
def _value(text, as_string):
    if as_string:
        return text
    try:
        return json.loads(text)
    except ValueError:
        return text


def main(argv=None):
    ap = argparse.ArgumentParser(prog="receipt.py", description="golem install receipt (docs/uninstall.md §2)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("path")
    a.add_argument("--kind", required=True, choices=KINDS)
    a.add_argument("--by", required=True)
    a.add_argument("--group", required=True)
    a.add_argument("--owner", choices=("user", "root"))
    a.add_argument("--moved-to", dest="moved_to")
    a.add_argument("--existed", action="store_true", help="the path was already there before golem placed it")
    p = sub.add_parser("prior")
    p.add_argument("key")
    p.add_argument("value", nargs="?")
    p.add_argument("--string", action="store_true", help="store VALUE as a string, never parse it as JSON")
    p.add_argument("--file", help="the value is this file's content (null if it does not exist)")
    sub.add_parser("prior-ufw")
    g = sub.add_parser("get")
    g.add_argument("key")
    s = sub.add_parser("apt-snapshot")
    s.add_argument("phase", choices=("before", "after"))
    d = sub.add_parser("deb")
    d.add_argument("name")
    q = sub.add_parser("apt-requested")
    q.add_argument("names", nargs="*")
    r = sub.add_parser("set-root")
    r.add_argument("dir")
    r.add_argument("--release")
    m = sub.add_parser("merge-pending")
    m.add_argument("--create", action="store_true", help="create the receipt if it does not exist yet")
    sub.add_parser("show")
    sub.add_parser("path")
    o = ap.parse_args(argv)

    if o.cmd == "add":
        add(o.path, o.kind, o.by, o.group, o.owner, o.moved_to, o.existed)
    elif o.cmd == "prior":
        if o.file:
            if _has_prior(o.key):            # ne relit même pas le fichier : le premier gagne
                return 0
            try:
                with open(o.file, encoding="utf-8", errors="replace") as f:
                    val = f.read()
            except FileNotFoundError:
                val = None
            prior(o.key, val)
        elif o.value is None:
            ap.error("prior needs VALUE or --file")
        else:
            prior(o.key, _value(o.value, o.string))
    elif o.cmd == "prior-ufw":
        prior("ufw", parse_ufw(sys.stdin.read()))
    elif o.cmd == "get":
        v = get_prior(o.key, _MISSING)
        if v is _MISSING:
            return 1
        print(json.dumps(v, ensure_ascii=False))
    elif o.cmd == "apt-snapshot":
        apt_snapshot(o.phase)
    elif o.cmd == "deb":
        deb(o.name)
    elif o.cmd == "apt-requested":
        apt_requested(o.names)
    elif o.cmd == "set-root":
        set_root(o.dir, o.release)
    elif o.cmd == "merge-pending":
        print(merge_pending(o.create))
    elif o.cmd == "show":
        print(json.dumps(load(), indent=1, ensure_ascii=False))
    elif o.cmd == "path":
        print(receipt_path())
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception as e:                       # le reçu ne casse jamais une install : on le dit, on sort 1
        print(f"receipt: {e}", file=sys.stderr)
        sys.exit(1)
