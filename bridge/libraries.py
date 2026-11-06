# SPDX-License-Identifier: GPL-3.0-or-later
"""Les composants libres que GoleM embarque — et ce qui est RÉELLEMENT installé sur cette machine.

Source : provision/components.json (docs/installer.md §5). Servi par GET /api/system/libraries
(System ▸ Licences ▸ Libraries) et lu par l'installateur pour la taille des packs. Une obligation
de la GPL avant d'être une page : dire ce qu'on embarque, sous quelle licence, et d'où ça vient.

Pur autant que possible : `check_one(comp, root, home, dpkg, pip_names)` ne touche pas au disque —
ce sont `installed_dpkg()` / `installed_pip()` / `glob_any()` qui lisent la machine, et les tests
les remplacent.
"""
import glob
import json
import os
import subprocess

from . import config as C

MANIFEST = os.path.join(C.ROOT, "provision", "components.json")


def load_manifest(path=None):
    with open(path or MANIFEST, encoding="utf-8") as f:
        d = json.load(f)
    return [c for c in (d.get("components") or []) if isinstance(c, dict) and c.get("id")]


def installed_dpkg():
    """{nom de paquet: version} des paquets installés (dpkg-query) ; {} hors Debian."""
    try:
        out = subprocess.run(["dpkg-query", "-W", "-f", "${Package}\t${Version}\t${Status}\n"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return {}
    res = {}
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) >= 3 and "installed" in parts[2] and "not-installed" not in parts[2]:
            res[parts[0]] = parts[1]
    return res


def installed_pip(root=None):
    """Modules importables du venv du bridge (noms de dossiers de site-packages)."""
    root = root or C.ROOT
    names = set()
    # le bridge (.venv) ET la transcription (.venv-transcribe, docs/archive/tablature-study.md) : deux venvs, un manifeste
    # Linux : .venv/lib/python3.x/site-packages ; Windows : .venv/Lib/site-packages (sans dossier de
    # version) — oublié, TOUT le Python s'affichait « missing » sous Windows, FastAPI compris (2026-10-03)
    sps = glob.glob(os.path.join(root, ".venv*", "lib", "python3*", "site-packages")) + \
          glob.glob(os.path.join(root, ".venv*", "Lib", "site-packages"))
    for sp in sorted(set(os.path.normcase(p) for p in sps)):
        for e in os.listdir(sp):
            if e.endswith(".dist-info") or e.endswith(".egg-info"):
                continue
            names.add(e.replace(".py", "").lower())
    return names


def _expand(p, root, home):
    p = p.replace("$ROOT", root)
    if p.startswith("~"):
        p = p.replace("~", home, 1)
    return os.path.expandvars(os.path.expanduser(p))      # %ProgramFiles%, %CommonProgramFiles% (Windows)


# ── WINDOWS (2026-10-03) ─────────────────────────────────────────────────────────────────────────
# Le manifeste ne connaissait que Linux (dpkg, ~/.lv2, ~/opt/REAPER) : sous Windows 51 composants sur 53
# s'affichaient « missing », REAPER et le NAM compris, qui jouaient. Sous Windows on lit `check_win`
# (le VST3 dans Common Files, l'exe dans Program Files) ; les contrôles du dépôt lui-même (Python, sons,
# JS) valent partout ; le reste n'est PAS utilisé par GoleM sous Windows — il le dit (« Linux only »)
# au lieu de se déclarer manquant : PipeWire ou Calf ne manquent pas à un Windows.
# macOS (2026-10-04, docs/platforms.md M3) : la même règle, avec `check_mac` — sans lui le Mac
# lisait les contrôles LINUX (dpkg, ~/.lv2) et déclarait tout « missing », REAPER compris.
NEUTRAL_KINDS = ("python", "asset", "js")
_DESKTOP_CHECK = {"win32": "check_win", "darwin": "check_mac"}


def check_for(comp, platform):
    """Le contrôle qui vaut sur cette plateforme, ou None si GoleM n'y utilise pas ce composant."""
    key = _DESKTOP_CHECK.get(platform)
    if key:
        if key in comp:
            return comp[key]
        return comp.get("check") if comp.get("kind") in NEUTRAL_KINDS else None
    return comp.get("check")


def glob_any(patterns, root, home):
    for pat in patterns or []:
        if glob.glob(_expand(pat, root, home), recursive=True):
            return True
    return False


def check_one(comp, root, home, dpkg, pip_names, exists=None, chk=None):
    """-> (installed: bool|None, version: str|None). None = pas vérifiable (pas de `check`)."""
    chk = (comp.get("check") if chk is None else chk) or {}
    exists = exists or (lambda pats: glob_any(pats, root, home))
    if chk.get("always"):
        return True, comp.get("version")
    for name in chk.get("which") or []:
        import shutil
        if shutil.which(name):
            return True, comp.get("version")
    for name in chk.get("dpkg") or []:
        if name in dpkg:
            return True, dpkg[name]
    for name in chk.get("pip") or []:
        if name.lower() in pip_names:
            return True, comp.get("version")
    if chk.get("glob"):
        return exists(chk["glob"]), comp.get("version")
    if chk:
        return False, comp.get("version")
    return None, comp.get("version")


def report(root=None, home=None, manifest=None, dpkg=None, pip_names=None, exists=None, platform=None):
    import sys
    platform = platform or sys.platform
    root = root or C.ROOT
    home = home or os.path.expanduser("~")
    comps = load_manifest(manifest)
    dpkg = (installed_dpkg() if platform.startswith("linux") else {}) if dpkg is None else dpkg
    pip_names = installed_pip(root) if pip_names is None else pip_names
    out = []
    for c in comps:
        chk = check_for(c, platform)
        base = {k: v for k, v in c.items() if k not in ("check", "check_win", "check_mac")}
        if chk is None and c.get("check") is not None:
            out.append({**base, "installed": None, "only": "linux"})
            continue
        inst, ver = check_one(c, root, home, dpkg, pip_names, exists, chk=chk or {})
        out.append({**base, "installed": inst, **({"version": ver} if ver else {})})
    n_ok = sum(1 for c in out if c["installed"])
    n_chk = sum(1 for c in out if c["installed"] is not None)
    licenses = sorted({c.get("license") or "?" for c in out})
    return {"components": out, "installed": n_ok, "checked": n_chk, "licenses": licenses}


def pack_sizes(manifest=None):
    """Taille (Mo) par pack optionnel de sons, depuis le manifeste — pour l'écran Taille."""
    sizes = {}
    for c in load_manifest(manifest):
        if c.get("pack"):
            sizes[c["pack"]] = sizes.get(c["pack"], 0) + int(c.get("mb") or 0)
    return sizes
