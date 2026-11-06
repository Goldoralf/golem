#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""La SYNTAXE de ce qui ne se compile jamais (audit 2026-10-15, lot 3) : l'app (Preact sans build) et les scripts
REAPER (Lua chargé par dofile) ne préviennent personne — une parenthèse manquante dans un module JS éteint toute
l'app, une erreur Lua ne se voit qu'au premier dofile dans REAPER.

    ./tools/check-syntax.py          # JS (node) + Lua (lupa, ou luac s'il est là)

Rend 1 au premier fichier fautif de chaque famille, avec l'erreur. Ne lance rien, n'écrit rien."""
import glob
import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def check_js():
    node = shutil.which("node")
    if not node:
        print("· JS : node absent — sauté")
        return []
    bad = []
    files = sorted(glob.glob(os.path.join(ROOT, "app", "*.js")) + glob.glob(os.path.join(ROOT, "app", "*.mjs")))
    for f in files:
        with open(f, "rb") as src:            # en MODULE : `node --check x.js` lirait du CommonJS et refuserait `import`
            r = subprocess.run([node, "--input-type=module", "--check"], stdin=src, capture_output=True, text=True)
        if r.returncode:
            bad.append((f, (r.stderr or r.stdout).strip().splitlines()[:4]))
    print(f"· JS : {len(files)} module(s), {len(bad)} en erreur")
    return bad


def check_lua():
    files = sorted(glob.glob(os.path.join(ROOT, "reaper", "Scripts", "*.lua")))
    luac = shutil.which("luac5.4") or shutil.which("luac")
    bad = []
    if luac:
        for f in files:
            r = subprocess.run([luac, "-p", f], capture_output=True, text=True)
            if r.returncode:
                bad.append((f, r.stderr.strip().splitlines()[:4]))
    else:
        try:
            from lupa import LuaRuntime
        except ImportError:
            print("· Lua : ni luac ni lupa (pip install -r requirements-dev.txt) — sauté")
            return []
        lua = LuaRuntime()
        load = lua.eval("function(src, name) local f, err = load(src, '@' .. name) return err end")
        for f in files:
            with open(f, encoding="utf-8", errors="surrogateescape") as src:
                err = load(src.read(), os.path.relpath(f, ROOT))     # COMPILE seulement : rien n'est exécuté
            if err:
                bad.append((f, [str(err)]))
    print(f"· Lua : {len(files)} script(s), {len(bad)} en erreur")
    return bad


def main():
    bad = check_js() + check_lua()
    for f, lines in bad:
        print(f"✗ {os.path.relpath(f, ROOT)}")
        for ln in lines:
            print("    " + ln)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
