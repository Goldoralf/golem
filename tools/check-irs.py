#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Balaye les réponses impulsionnelles installées (assets/irs/**.wav) et dit lesquelles portent une
impulsion tardive — un écho par note une fois convoluées (Sunfunk, 2026-09-14 : les 16 IR des packs
Palmer 2x12 répétaient chaque note à 480 ms, à −22 dB, delay bypassé). Même lecture que la garde
du compile (`compile_rig.ir_late_impulse`) : le fichier, jamais une déclaration.

    ./tools/check-irs.py            # verdict par pack
    ./tools/check-irs.py --files    # détail par fichier
"""
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bridge import compile_rig as cr  # noqa: E402

files = sorted(glob.glob(os.path.join(ROOT, "assets", "irs", "**", "*.wav"), recursive=True))
packs, bad_files = {}, []
for f in files:
    pack = os.path.relpath(f, os.path.join(ROOT, "assets", "irs")).split(os.sep)[1] if os.sep in os.path.relpath(f, os.path.join(ROOT, "assets", "irs")) else "?"
    try:
        late = cr.ir_late_impulse(f)
    except Exception as e:
        late = ("illisible", str(e)[:40])
    p = packs.setdefault(pack, {"n": 0, "bad": 0, "worst": None})
    p["n"] += 1
    if late:
        p["bad"] += 1; bad_files.append((pack, os.path.basename(f), late))
        if late[0] != "illisible" and (p["worst"] is None or late[1] > p["worst"][1]):
            p["worst"] = late
for pack, p in sorted(packs.items(), key=lambda kv: -kv[1]["bad"]):
    mark = "✗" if p["bad"] else "✓"
    worst = f" — pire : {p['worst'][0]} ms à {p['worst'][1]} dB" if p["worst"] else ""
    print(f"{mark} {pack[:60]:60s} {p['bad']:2d}/{p['n']:<3d} avec écho{worst}")
if "--files" in sys.argv:
    for pack, name, late in bad_files:
        print(f"   {pack[:40]:40s} {name[:50]:50s} {late}")
n_bad = sum(p["bad"] for p in packs.values())
print(f"\n{len(files)} IR, {n_bad} avec impulsion tardive — la garde du compile les coupe dans le cache ; "
      f"le fichier de la bibliothèque n'est pas touché.")
sys.exit(1 if n_bad else 0)
