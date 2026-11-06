#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Étape FACTICE de l'installateur (--dry) : écrit ce qu'une vraie étape écrirait, en 2 s, sans rien
toucher. Sert aux écrans, aux tests Playwright et à la démonstration — sous Linux comme sous Windows
(c'était un script bash ; Windows n'a pas bash). `GOLEM_DRY_FAIL=<étape>` fait échouer cette étape
(pour voir le bouton Retry). L'étape « system » de Linux joue aussi les marqueurs de phase de provision/install.sh
(installer/phases.py) ; `GOLEM_DRY_WARN=nam,vital` y ajoute ces manques non fatals (pour voir les ⚠ et le ↻), que
`dry_step.py retry-<id>` « répare ».

    python3 installer/dry_step.py <étape>

Le désinstallateur (installer/uninstaller.py, --dry) a ses deux simulations, qui écrivent EXACTEMENT ce qu'écrivent
les vraies commandes, pour que le serveur lise la même chose dans les deux modes :
    python3 installer/dry_step.py backup DEST [--secrets]          ≈ python -m bridge.backup_cli full --json
    python3 installer/dry_step.py uninstall-run SELECT PLAN [--attempt N]   ≈ provision/uninstall.py run --json
`GOLEM_DRY_FAIL=backup` fait échouer la vérification de la sauvegarde ; `GOLEM_DRY_FAIL_ITEM=<id>` fait échouer
cet élément à la première tentative (pour voir Retry).
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def reaper_pin():
    # la version de la simulation SUIT le pin du provisioning : écrite en dur, elle vieillit en
    # silence et l'écran de démonstration ment
    if sys.platform == "win32":
        try:
            return json.load(open(os.path.join(ROOT, "provision", "windows", "pins.json")))["reaper"]["version"]
        except Exception:
            return "7.x"
    try:
        t = open(os.path.join(ROOT, "provision", "install-reaper.sh")).read()
        return re.search(r'REAPER_VERSION="\$\{REAPER_VERSION:-([\d.]+)\}"', t).group(1)
    except Exception:
        return "7.x"


def lines(*ls):
    for line in ls:
        print(line, flush=True)
        time.sleep(0.25)


def dry_backup(args):
    """La sauvegarde complète, simulée : rien n'est écrit dans DEST."""
    dest = os.path.abspath(os.path.expanduser(args[0] if args else "~/golem-backup"))
    secrets = "--secrets" in args
    time.sleep(1.5)
    ts = time.strftime("%Y%m%d-%H%M%S")
    if os.environ.get("GOLEM_DRY_FAIL") == "backup":
        print(json.dumps({"ok": False, "error": "golem-all-%s.zip: presets/clean.json: sha256 mismatch (simulated)" % ts}))
        sys.exit(1)
    files = [("golem-all-%s.zip" % ts, 812_000_000), ("golem-songs-%s.zip" % ts, 46_000_000),
             ("identity/serial.json", 120), ("identity/reaper-license.rk", 900)]
    if secrets:
        files += [("secrets/integrations.json", 640), ("secrets/auth-devices.json", 1800),
                  ("secrets/network.json", 420), ("secrets/.env", 210)]
    files.append(("README.txt", 2100))
    print(json.dumps({"ok": True, "dest": dest, "files": [{"path": p, "size": n} for p, n in files],
                      "verified": {files[0][0]: 1834, files[1][0]: 27}, "secrets": secrets,
                      "estimated": 900_000_000, "dry": True}, indent=1))


def _uninstall_step(it):
    # l'étape du moteur (provision/uninstall.py run) pour un élément : même ordre que le §5
    if it.get("id") == "golem:install-folder":
        return "folder"
    if it.get("group") == "apt":
        return "apt"
    if it.get("privilege") == "root":
        return "root"
    if it.get("group") in ("reaper-links", "reaper-ini", "reaper"):
        return "reaper"
    return "user"


def dry_uninstall(args):
    """La désinstallation, simulée : une ligne JSON par action, comme `uninstall.py run --json`. Rien n'est touché."""
    sel, planf = args[0], args[1]
    attempt = int(args[args.index("--attempt") + 1]) if "--attempt" in args else 1
    ids = json.load(open(sel, encoding="utf-8"))
    full = json.load(open(planf, encoding="utf-8"))
    plan = {i["id"]: i for i in full.get("items", [])}
    fail = os.environ.get("GOLEM_DRY_FAIL_ITEM") if attempt == 1 else None

    def out(step, item, ok, msg, **extra):
        print(json.dumps({"step": step, "item": item, "ok": ok, "msg": msg, **extra}), flush=True)
        time.sleep(0.12)
    out("stop", None, True, "autostart off (dry)")
    out("stop", None, True, "engine stopped (dry)")
    failed = []
    for step in ("root", "apt", "reaper", "user", "folder"):
        if step == "reaper" and any(_uninstall_step(plan.get(i) or {"id": i}) == "apt" for i in ids):
            # comme le moteur : une ligne de bilan des dépendances après les paquets choisis
            n = len(full.get("apt_deps") or [])
            out("apt", None, True, "%d dependencies removed (dry)" % n, deps=n)
        for i in ids:
            it = plan.get(i) or {"id": i}
            if _uninstall_step(it) != step:
                continue
            if i == fail:
                failed.append(i)
                out(step, i, False, "simulated failure (dry)")
            else:
                out(step, i, True, {"remove": "removed", "disable": "disabled and removed", "revert": "reverted",
                                    "restore": "restored", "purge": "purged"}.get(it.get("action"), "done") + " (dry)")
    out("receipt", None, True, "receipt rewritten with what remains (dry)" if failed else "receipt deleted: golem is uninstalled (dry)")
    out("done", None, not failed, "%d item(s) failed: %s" % (len(failed), ", ".join(failed)) if failed
        else "everything chosen was removed")
    sys.exit(1 if failed else 0)


def main():
    step = sys.argv[1] if len(sys.argv) > 1 else "?"
    if step == "backup":
        return dry_backup(sys.argv[2:])
    if step == "uninstall-run":
        return dry_uninstall(sys.argv[2:])
    rv = reaper_pin()
    win = sys.platform == "win32"
    if step == "reaper":
        if win:
            lines(f"▶ Reaper {rv}", f"→ downloading reaper{rv.replace('.', '')}_x64-install.exe (dry)",
                  "→ sha256 OK (pinned)", "✓ Reaper in C:\\Program Files\\REAPER (x64) (dry)")
        else:
            lines(f"▶ Reaper {rv}", f"→ downloading reaper{rv.replace('.', '')}_linux_x86_64.tar.xz (dry)",
                  "→ sha256 OK (pinned)", "→ installed in ~/opt/REAPER (dry)")
    elif step == "source":
        lines("→ copy (dry) → target", "→ origin set to github.com/Goldoralf/golem")
    elif step == "system":
        if win:
            lines("→ Windows asks your permission once (UAC) (dry)", "▶ Microsoft Visual C++ runtime (x64)",
                  "→ signature OK (Microsoft Corporation)", "▶ NeuralAmpModeler VST3 0.7.13 (the amp and cab core)",
                  "→ sha256 OK (pinned)", "▶ Firewall: Reaper accepts nothing from the network (dry)", "✅ system step done")
        else:
            warn = set(filter(None, os.environ.get("GOLEM_DRY_WARN", "").split(",")))
            lines("@@phase packages", "▶ Paquets apt", "→ 38 packages (dry)",
                  "@@phase realtime", "▶ Temps-réel : groupe audio + limits",
                  "@@phase reaper", "▶ Reaper", "→ already installed",
                  "@@phase plugins", "▶ Plugins LV2 (releases GitHub : NAM, AIDA-X, Ratatouille, Aether)",
                  "▶ Plugins LV2 des blocs FX", "▶ sfizz",
                  *(["@@warn |Vital is missing — the synth of the Keys lane stays silent. It needs a free vital.audio "
                     "account: get it from vital.audio, golem finds it at its next start."] if "vital" in warn else []),
                  "@@phase build", "@@sub IR convolver fix (cab block) — 1 of 4", "warning: unused variable (dry)",
                  "@@sub NAM fix (amp and pedal blocks) — 2 of 4",
                  *(["  ⚠ NAM corrigé NON installé (dry)", "@@warn nam|The NAM fix could not be built — amps play with the "
                     "standard NAM, which can stop the engine on very fast patch changes."] if "nam" in warn else []),
                  "@@sub Prisma (Grit block) — 3 of 4", "@@sub Spectral blocks (Spectral Comp, Stretch, Freeze) — 4 of 4",
                  "@@phase golem", "▶ Config Reaper (OSC + device audio)", "▶ Bridge Python (venv + dépendances)",
                  "@@phase sounds", "▶ Sons : NAM / IR + piano Salamander (dry)",
                  "@@sub Piano (Salamander) — 1 of 2", "@@progress 0 1058", "@@progress 300 1058", "@@progress 707 1058",
                  "@@sub Guitar (Shinyguitar) — 2 of 2", "@@progress 900 1058", "@@progress 1058 1058",
                  "✅ Provisioning complete.")
    elif step == "bridge":
        lines("→ venv + bridge/requirements.lock (dry)", "→ scripts and JSFX copied to %APPDATA%\\REAPER (dry)",
              "→ OSC surface and Dummy Audio in reaper.ini (dry)", "golem is ready (dry).")
    elif step == "sounds":
        lines("↓ golem reference DIs (dry)", "✓ reference DIs (dry)")
    elif step.startswith("retry-"):
        lines(f"→ {step[6:]}: building again (dry)", f"✓ {step[6:]} installed (dry)")
    elif step.startswith("profile"):
        if win:
            lines("→ shortcut Start menu\\golem.lnk (dry)", "→ shortcut Desktop\\golem Server.lnk (dry)")
        else:
            lines("→ launcher installed in ~/.local/share/applications (dry)")
    elif step == "start":
        lines("→ bridge lancé (:8770) (dry)", "→ Reaper lancé (dry)")
    else:
        lines(f"→ {step} (dry)")
    if os.environ.get("GOLEM_DRY_FAIL") == step:
        print(f"✗ simulated failure in {step}", flush=True)
        sys.exit(3)


if __name__ == "__main__":
    main()
