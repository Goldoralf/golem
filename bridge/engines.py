# SPDX-License-Identifier: GPL-3.0-or-later
"""Moteurs audio — lecture des descripteurs config/engines/*.json (docs/audio-engine-choice.md §5).

COQUILLE (2026-10-06) : la page Settings ▸ Engines ▸ Audio et l'écran de l'installateur montrent les
moteurs, un seul est sélectionnable (Reaper). Aucune bascule n'existe : choisir un AUTRE moteur
que celui qui tourne est le lot E3 (arrêter, démarrer l'autre, reconstruire, vérifier, revenir
seul en cas d'échec). Ce module ne fait que DIRE ce qui est choisi et ce qui serait possible.

Le code ne connaît aucun moteur par son nom : il lit les descripteurs (même doctrine que les
pédaliers, docs/pedalboards.md). Ajouter un moteur = poser un fichier, pas toucher ce code.

⚠ BIBLIOTHÈQUE STANDARD SEULEMENT, et aucun import de bridge.* au niveau module : l'installateur
(installer/server.py, avant toute dépendance) importe ce fichier tel quel, avec SA racine.
"""
import json
import os
import sys
import time

CHOICE_FILE = "engine.json"                     # config/engine.json — état LOCAL, gitignoré


def _root(root=None):
    if root:
        return root
    from . import config as C                   # paresseux : l'installateur passe toujours root
    return C.ROOT


def _os_key(platform=None):
    p = platform or sys.platform
    return p if p in ("win32", "darwin") else "linux"


def _read(path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def features(root=None):
    """[(id, label)] dans l'ordre d'affichage."""
    d = _read(os.path.join(_root(root), "config", "engines", "features.json"), {})
    return [tuple(f) for f in d.get("features") or [] if isinstance(f, list) and len(f) == 2]


def availability(desc, platform=None):
    """(sélectionnable ici ?, raison si non). Il faut les DEUX : le moteur est livré (selectable)
    ET il existe pour ce système (platforms.<os>.available)."""
    plat = (desc.get("platforms") or {}).get(_os_key(platform)) or {}
    if not desc.get("selectable"):
        return False, plat.get("reason") or desc.get("unavailable_reason") or "Not available yet"
    if not plat.get("available"):
        return False, plat.get("reason") or "Not available on this system"
    return True, None


def descriptors(root=None, platform=None):
    """Tous les moteurs connus, triés, chacun avec `available` et `reason` calculés pour ce système."""
    d = os.path.join(_root(root), "config", "engines")
    out = []
    try:
        names = sorted(os.listdir(d))
    except OSError:
        names = []
    for n in names:
        if not n.endswith(".json") or n == "features.json":
            continue
        desc = _read(os.path.join(d, n), None)
        if not isinstance(desc, dict) or desc.get("id") != n[:-5]:
            continue                             # l'id suit le nom du fichier, sinon on l'ignore
        ok, why = availability(desc, platform)
        out.append({**{k: v for k, v in desc.items() if not k.startswith("_")}, "available": ok, "reason": why})
    return sorted(out, key=lambda e: (e.get("order", 99), e["id"]))


def default_id(root=None, platform=None):
    """Le moteur proposé par défaut : celui marqué `default` et disponible ici, sinon le premier disponible."""
    engines = [e for e in descriptors(root, platform) if e["available"]]
    for e in engines:
        if e.get("default"):
            return e["id"]
    return engines[0]["id"] if engines else None


def current(root=None, platform=None):
    """Le moteur choisi sur cette machine (config/engine.json). Absent ou devenu indisponible : le
    défaut — un rack installé avant cette page n'a pas le fichier, et il tourne sur Reaper."""
    r = _root(root)
    choice = (_read(os.path.join(r, "config", CHOICE_FILE), {}) or {}).get("engine")
    ok = {e["id"] for e in descriptors(r, platform) if e["available"]}
    return choice if choice in ok else default_id(r, platform)


def write_choice(engine_id, root=None, set_by="bridge", platform=None):
    """Écrit config/engine.json après vérification. Lève ValueError si le moteur n'est pas
    sélectionnable ici. N'ARRÊTE ni ne DÉMARRE rien : la bascule est le lot E3."""
    r = _root(root)
    desc = next((e for e in descriptors(r, platform) if e["id"] == engine_id), None)
    if desc is None:
        raise ValueError(f"unknown engine: {engine_id}")
    if not desc["available"]:
        raise ValueError(f"{desc.get('name', engine_id)}: {desc['reason']}")
    os.makedirs(os.path.join(r, "config"), exist_ok=True)
    path = os.path.join(r, "config", CHOICE_FILE)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"engine": engine_id, "set_by": set_by, "at": time.strftime("%Y-%m-%d %H:%M")}, f, indent=1)
    os.replace(tmp, path)
    return engine_id
