#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""golem doctor — Health et ses réparations en ligne de commande (docs/assistant.md §3).

La voie de secours quand l'écran ne répond plus : les MÊMES faits (GET /api/health/facts), les MÊMES incidents et le
MÊME registre d'actions que Settings ▸ Health — `golem doctor` n'a aucune réparation à lui. Bibliothèque standard
seulement : il doit tourner quand le venv ou l'écran sont cassés. Bridge injoignable : il dit ce qu'il voit de
l'extérieur (le port, le processus REAPER) et comment relancer.

    golem doctor                      # les faits, les incidents ouverts, les réparations proposées
    golem doctor --list               # le registre : ce que cette machine sait faire
    golem doctor --fix set_buffer --param size=256 [--yes]
                                      # la feuille, la confirmation, puis la vérification suivie jusqu'au verdict
Codes de sortie : 0 tout va bien · 1 quelque chose à regarder (ou une réparation ratée) · 2 golem ne répond pas."""
import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

PORT = int(os.environ.get("GOLEM_PORT") or os.environ.get("PORT") or 8770)
BASE = f"http://127.0.0.1:{PORT}"
MARK = {"ok": "✓", "warn": "!", "bad": "✗", "wait": "·", "on": "…"}


def call(path, body=None, timeout=15):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, headers={"content-type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {"error": str(e)}


def reachable():
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=2):
            return True
    except OSError:
        return False


def reaper_running():
    try:
        if sys.platform == "win32":
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq reaper.exe"], capture_output=True, text=True, timeout=5).stdout
            return "reaper.exe" in out.lower()
        # par NOM EXACT de processus : jamais par motif de ligne de commande (il se trouverait lui-même)
        return subprocess.run(["pgrep", "-x", "reaper" if sys.platform != "darwin" else "REAPER"],
                              capture_output=True, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def offline():
    print("✗ golem does not answer on port %d." % PORT)
    print("  bridge port open: %s" % ("yes — it answers slowly or not at all" if reachable() else "no — the bridge is not running"))
    r = reaper_running()
    print("  REAPER running:    %s" % ({True: "yes", False: "no", None: "unknown"}[r]))
    print("\nStart golem with `golem` (window) or `golem server` (no window); `golem restart` if it hangs.")
    if sys.platform.startswith("linux"):
        print("Its logs: /tmp/golem-bridge.log (the bridge) and /tmp/golem-reaper.log (REAPER's stderr)")
    return 2


def show():
    st, doc = call("/api/health/facts?fresh=1")
    if st != 200:
        print(f"✗ golem answered {st}: {doc.get('error', '')}")
        return 2
    v = doc.get("verdict") or {}
    print(f"{MARK.get(v.get('level'), '·')} {v.get('title', '')}")
    if v.get("text"):
        print(f"  {v['text']}")
    print()
    for f in doc.get("facts") or []:
        print(f"  {MARK.get(f['level'], '·')} {f['name']:<20} {f['text']}")
        r = f.get("repair")
        if r and f["level"] in ("warn", "bad"):
            params = " ".join(f"--param {k}={v}" for k, v in (r.get("params") or {}).items())
            how = f"golem doctor --fix {r['action']}" + (f" {params}" if params else "")
            print(f"      → {r['title']}: " + (f"not now ({r['blocked']})" if r.get("blocked") else how))
    st, inc = call("/api/health/incidents?limit=10")
    opened = [i for i in (inc.get("items") or []) if i.get("state") != "closed"] if st == 200 else []
    if opened:
        print("\nOpen incidents:")
        for i in opened:
            print(f"  ✗ {i['title']} — {i.get('detail', '')} ({i['state']})")
    return 0 if v.get("level") in ("ok", "wait") else 1


def listing():
    st, doc = call("/api/health/fixes")
    if st != 200:
        return offline()
    for a in doc.get("actions") or []:
        props = (a.get("params") or {}).get("properties") or {}
        ps = ", ".join(f"{k}={'|'.join(map(str, p['enum'])) if 'enum' in p else p.get('type')}" for k, p in props.items())
        print(f"{a['name']:<16} {a['risk']:<7} {'live ok' if a['live_allowed'] else 'not live'}  {a['label']}" + (f"  ({ps})" if ps else ""))
        print(f"{'':<16} {a['description']}")
    return 0


def parse_params(items):
    out = {}
    for it in items or []:
        k, _, v = it.partition("=")
        out[k] = int(v) if v.lstrip("-").isdigit() else v
    return out


def fix(action, params, yes):
    st, plan = call("/api/health/fix", {"action": action, "params": params})
    if st != 200:
        print(f"✗ {plan.get('error', 'refused')}")
        return 1
    print(plan["title"])
    if plan.get("why"):
        print(f"  {plan['why']}")
    if plan.get("before") and plan.get("after"):
        print(f"  now:   {plan['before']['value']} {plan['before'].get('sub', '')}")
        print(f"  after: {plan['after']['value']} {plan['after'].get('sub', '')}")
    for c in plan.get("costs") or []:
        print(f"  ↻ {c}")
    if plan.get("verify"):
        print(f"  ✓ {plan['verify']}")
    if plan.get("undo"):
        print(f"  ⤺ {plan['undo']}")
    if plan.get("blocked"):
        print(f"\n✗ Not now: {plan['blocked']}.")
        return 1
    if not yes:
        if not sys.stdin.isatty():
            print("\nNot applied: pass --yes to confirm without a terminal.")
            return 1
        if input(f"\n{plan['apply_label']}? [y/N] ").strip().lower() not in ("y", "yes"):
            print("Nothing changed.")
            return 0
    # l'incident ouvert de ce fait, s'il y en a un : la réparation y sera rangée, comme depuis l'écran
    incident = None
    st, doc = call("/api/health/facts")
    for f in (doc.get("facts") or []) if st == 200 else []:
        if (f.get("repair") or {}).get("action") == action and f.get("incident"):
            incident = f["incident"]
    st, r = call("/api/health/fix", {"action": action, "params": params, "confirm": True, "by": "doctor", "incident": incident})
    if st != 200:
        print(f"✗ {r.get('error', 'refused')}")
        return 1
    last_text = None
    while True:
        time.sleep(1)
        try:
            st, s = call("/api/health/fix", timeout=5)
        except (OSError, urllib.error.URLError):
            continue                                  # le bridge peut sauter une seconde pendant un redémarrage
        cur, last = s.get("current"), s.get("last")
        if cur:
            if cur.get("text") != last_text:
                last_text = cur.get("text")
                print(f"  … {last_text}")
            continue
        if last and last.get("id") == r["fix"]["id"]:
            ok = last.get("phase") == "done"
            print(f"{'✓' if ok else '✗'} {last.get('text', '')}")
            return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(prog="golem doctor", description="Health and its fixes, from the command line.")
    ap.add_argument("--list", action="store_true", help="what this machine knows how to fix")
    ap.add_argument("--fix", metavar="ACTION", help="describe, confirm, apply and verify one fix")
    ap.add_argument("--param", action="append", metavar="KEY=VALUE", help="a parameter of the fix (repeatable)")
    ap.add_argument("--yes", action="store_true", help="apply without asking")
    a = ap.parse_args()
    try:
        if a.list:
            return listing()
        if a.fix:
            return fix(a.fix, parse_params(a.param), a.yes)
        return show()
    except (urllib.error.URLError, ConnectionError, socket.timeout, TimeoutError):
        return offline()


if __name__ == "__main__":
    sys.exit(main())
