# SPDX-License-Identifier: GPL-3.0-or-later
"""Le reçu d'installation vu du bridge (docs/uninstall.md §2) — une cale vers provision/receipt.py.

Ce que le bridge écrit À L'EXÉCUTION dans des endroits partagés (le buffer et la carte dans reaper.ini, la
licence REAPER, les versions de REAPER) note son état d'avant par le même helper, chargé par son CHEMIN
(provision/ n'est pas un paquet du bridge). Deux règles :
  · jamais d'exception : un reçu raté ne fait pas échouer une route ;
  · on n'écrit que dans un reçu QUI EXISTE. Une machine installée avant le reçu n'en a pas ; en créer un ici
    n'y mettrait que des miettes, et la désinstallation se croirait en mode « reçu » (§3) sur un reçu vide.
Linux et Windows (§9.2 : %LOCALAPPDATA%\\GoleM\\install-receipt.json) ; macOS suivra."""
import importlib.util
import logging
import os
import sys

from . import config as C

_log = logging.getLogger("golem.receipt")
_MOD = None


def _mod():
    global _MOD
    if _MOD is None:
        spec = importlib.util.spec_from_file_location("golem_receipt", os.path.join(C.ROOT, "provision", "receipt.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _MOD = m
    return _MOD


def _usable():
    if not (sys.platform.startswith("linux") or sys.platform == "win32"):
        return None
    try:
        m = _mod()
        return m if m.exists() else None
    except Exception as e:
        _log.warning(f"install receipt unavailable ({e})")
        return None


def prior(key, value):
    """prior.<key> = value, si le reçu existe et que la clé n'y est pas encore (le premier gagne)."""
    m = _usable()
    if m is None:
        return False
    try:
        return m.prior(key, value)
    except Exception as e:
        _log.warning(f"install receipt: prior {key} not recorded ({e})")
        return False


def add(path, kind, group, owner=None, by="bridge"):
    m = _usable()
    if m is None:
        return None
    try:
        return m.add(path, kind, by, group, owner)
    except Exception as e:
        _log.warning(f"install receipt: {path} not recorded ({e})")
        return None


def path():
    """Le chemin du reçu QUAND il existe (None sinon) — à passer en paramètre au script élevé de Windows
    (install-system.ps1 -Receipt) : un administrateur ne résout jamais le %LOCALAPPDATA% de l'utilisateur."""
    m = _usable()
    return m.receipt_path() if m is not None else None


def merge_pending():
    """Verse les fragments que le script élevé a déposés à côté du reçu (§9.2). Jamais d'exception."""
    m = _usable()
    if m is None:
        return 0
    try:
        return m.merge_pending()
    except Exception as e:
        _log.warning(f"install receipt: pending fragments not merged ({e})")
        return 0


def ini_value(path, key):
    """Valeur actuelle de <key> dans [reaper] de reaper.ini (None si absente) — pour la noter AVANT de l'écrire."""
    try:
        with open(path, encoding="latin-1") as f:
            lines = f.read().splitlines()
    except OSError:
        return None
    sect = None
    for line in lines:
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            sect = s[1:-1]
            continue
        if sect == "reaper" and "=" in line and line.split("=", 1)[0].strip() == key:
            return line.split("=", 1)[1]
    return None
