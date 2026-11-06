# SPDX-License-Identifier: GPL-3.0-or-later
"""Le boost CPU sous Windows : le pendant du gouverneur « performance » du rack (provision/perf-mode.sh).

Linux bascule le gouverneur cpufreq (powersave -> performance), en root. Windows a l'équivalent en
PLANS D'ALIMENTATION, qu'un utilisateur change SANS droits (`powercfg /setactive`) :

  · boost ON  : on retient le plan actif (config/.power.json), puis on passe sur « Performance » — le
                plan du fabricant quand il existe (le poste de dev : Silent / Utilisation normale /
                Performance / Turbo, décision 2026-10-03 : Performance), sinon « Performances
                élevées » de Windows ;
  · boost OFF : on remet le plan retenu (sinon « Utilisation normale »).

Le reste du bridge parle « gouverneur » (`performance` ou non) : governor() le rend sous la même forme,
le Dashboard et la bascule de mode (modes.perf_boost) marchent tels quels.

⚠ powercfg parle la langue de Windows : on ne lit que le GUID et le nom entre parenthèses ; « * » marque
l'actif. Un logiciel du fabricant (type NitroSense) peut reprendre la main sur le plan : governor() relit
l'actif à chaque fois, l'écran dit donc toujours la vérité.
"""
import json
import os
import re
import subprocess

from . import config as C

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HIGH_PERF = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"     # « Performances élevées » de Windows
BALANCED = "381b4222-f694-41f0-9685-ff5bb260df2e"      # « Utilisation normale »


def _powercfg(*args):
    try:
        p = subprocess.run(["powercfg", *args], capture_output=True, timeout=10, creationflags=NO_WINDOW)
        out = p.stdout or b""
        for enc in ("utf-8", "cp850", "mbcs"):
            try:
                return p.returncode, out.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return p.returncode, out.decode("latin-1")
    except Exception as e:
        return 1, str(e)


def schemes():
    """[{guid, name, active}] — les plans d'alimentation du poste."""
    rc, out = _powercfg("/list")
    rows = []
    for line in out.splitlines():
        m = re.search(r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s+\((.+?)\)\s*(\*)?\s*$", line, re.I)
        if m:
            rows.append({"guid": m.group(1).lower(), "name": m.group(2), "active": bool(m.group(3))})
    return rows


def performance_scheme(rows=None):
    """Le plan du boost : « Performance » (fabricant) d'abord, sinon « Performances élevées » de Windows."""
    rows = schemes() if rows is None else rows
    exact = next((r for r in rows if r["name"].strip().lower() == "performance"), None)
    return exact or next((r for r in rows if r["guid"] == HIGH_PERF), None)


def _state_path():
    return os.path.join(C.CONFIG_DIR, ".power.json")


def governor():
    """« performance » quand le plan du boost est actif, « balanced » sinon, None si powercfg ne répond pas."""
    rows = schemes()
    if not rows:
        return None
    perf = performance_scheme(rows)
    active = next((r for r in rows if r["active"]), None)
    return "performance" if perf and active and active["guid"] == perf["guid"] else "balanced"


def set_boost(on):
    """Rend (ok, message). ON : retient le plan courant puis active « Performance ». OFF : le rend."""
    rows = schemes()
    perf = performance_scheme(rows)
    active = next((r for r in rows if r["active"]), None)
    if on:
        if not perf:
            return False, "no Performance power plan on this computer"
        if active and active["guid"] != perf["guid"]:
            try:
                os.makedirs(C.CONFIG_DIR, exist_ok=True)
                with open(_state_path(), "w", encoding="utf-8") as f:
                    json.dump({"before": active["guid"], "before_name": active["name"]}, f)
            except OSError:
                pass
            # le reçu d'installation (docs/uninstall.md §9.2) : le plan d'AVANT golem, le premier gagne — la
            # désinstallation le remet. config/.power.json reste celui du boost OFF (il suit chaque bascule).
            from . import install_receipt
            install_receipt.prior("power_scheme", {"guid": active["guid"], "name": active["name"]})
        rc, out = _powercfg("/setactive", perf["guid"])
        return rc == 0, f"power plan: {perf['name']}" if rc == 0 else out.strip()
    try:
        with open(_state_path(), encoding="utf-8") as f:
            before = json.load(f).get("before")
    except (OSError, ValueError):
        before = None
    if not before or not any(r["guid"] == before for r in rows) or (perf and before == perf["guid"]):
        before = BALANCED
    rc, out = _powercfg("/setactive", before)
    name = next((r["name"] for r in rows if r["guid"] == before), before)
    return rc == 0, f"power plan: {name}" if rc == 0 else out.strip()
