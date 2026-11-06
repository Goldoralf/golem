#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Détoure le fond uni sombre d'une icône → PNG transparent (alpha).

Flood-fill depuis les 4 coins : seuls les pixels de fond CONTIGUS aux bords
deviennent transparents (ne troue pas l'intérieur de l'icône).

Usage : python3 tools/key_bg.py in.png out.png [--thresh 60]
        python3 tools/key_bg.py --dir assets/icons   # détoure tous les *.png en place (suffixe -a.png)
"""
import sys, glob, os
from PIL import Image, ImageDraw


def key(in_path, out_path, thresh=70):
    im = Image.open(in_path).convert("RGBA")
    w, h = im.size
    # masque RGB pour flood-fill (Pillow floodfill agit sur RGB)
    rgb = im.convert("RGB")
    seen = Image.new("L", (w, h), 0)
    px = rgb.load()
    mark = seen.load()

    def lum(p):
        return 0.299 * p[0] + 0.587 * p[1] + 0.114 * p[2]

    # BFS depuis les bords : marque le fond sombre contigu
    from collections import deque
    q = deque()
    for x in range(w):
        for y in (0, h - 1):
            q.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            q.append((x, y))
    while q:
        x, y = q.popleft()
        if x < 0 or y < 0 or x >= w or y >= h or mark[x, y]:
            continue
        if lum(px[x, y]) > thresh:
            continue
        mark[x, y] = 255
        q.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])

    out = im.copy()
    op = out.load()
    for y in range(h):
        for x in range(w):
            if mark[x, y]:
                op[x, y] = (0, 0, 0, 0)
    out.save(out_path)
    return out_path


def main():
    if sys.argv[1] == "--dir":
        for p in sorted(glob.glob(os.path.join(sys.argv[2], "*.png"))):
            if p.endswith("-a.png"):
                continue
            out = p[:-4] + "-a.png"
            print(key(p, out))
        return
    thresh = 70
    if "--thresh" in sys.argv:
        thresh = int(sys.argv[sys.argv.index("--thresh") + 1])
    print(key(sys.argv[1], sys.argv[2], thresh))


if __name__ == "__main__":
    main()
