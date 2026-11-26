#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes library/catalog/anim-stills.json: the STILL IMAGE of each effect of the default animation pack.

docs/anim-packs.md §8. When Live tiles are still, a tile shows this image instead of a paused animation. Each image is an
SVG with a transparent background, drawn over the tile colour; `currentColor` is replaced by the tile colour when drawn.
Square viewBox 200×200, shown with background-size: cover; what matters stays in the central 200×120 band.

    ./tools/make-anim-stills.py          # rewrites the file
    ./tools/make-anim-stills.py --check  # exit 1 if the file differs (CI)
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "library" / "catalog" / "anim-stills.json"
HEAD = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 200 200' preserveAspectRatio='xMidYMid slice'>"


def svg(body):
    return HEAD + body + "</svg>"


def circles(pts, fill, op):
    return "".join(f"<circle cx='{x}' cy='{y}' r='{r}' fill='{fill}' fill-opacity='{op}'/>" for x, y, r in pts)


# les fonds sont TRANSPARENTS : la couleur de la case (--pc) est peinte dessous ; `currentColor` = cette couleur
STILLS = {
    # anneaux concentriques : blancs (visibles sur une case allumée), le 1er à la couleur de la case
    "pulse": svg("".join(f"<circle cx='100' cy='100' r='{r}' fill='none' stroke='#fff' stroke-opacity='{op}' stroke-width='2'/>"
                         for r, op in ((44, .34), (66, .24), (88, .16), (110, .1), (132, .06)))
                 + "<circle cx='100' cy='100' r='22' fill='none' stroke='currentColor' stroke-width='5'/>"
                 + "<circle cx='100' cy='100' r='22' fill='none' stroke='#fff' stroke-opacity='.5' stroke-width='2'/>"
                 + "<circle cx='100' cy='100' r='5' fill='#fff' fill-opacity='.6'/>"),
    # un tracé d'électrocardiogramme
    "heartbeat": svg("<path d='M-10 112H72l9-20 11 40 10-56 9 36 7-10h92' fill='none' stroke='#ff8a7a' stroke-opacity='.75' "
                     "stroke-width='2.4' stroke-linejoin='round' stroke-linecap='round'/>"
                     "<path d='M-10 112H72l9-20 11 40 10-56 9 36 7-10h92' fill='none' stroke='#ff8a7a' stroke-opacity='.18' "
                     "stroke-width='9' stroke-linejoin='round'/>"),
    # deux sinusoïdes au pied
    "wave": svg("<path d='M-10 128 Q15 106 40 128 T90 128 T140 128 T190 128 T240 128' fill='none' stroke='#fff' stroke-opacity='.4' stroke-width='2'/>"
                "<path d='M-10 140 Q15 122 40 140 T90 140 T140 140 T190 140 T240 140' fill='none' stroke='#fff' stroke-opacity='.18' stroke-width='1.6'/>"),
    # un reflet en diagonale
    "sheen": svg("<defs><linearGradient id='s' x1='0' y1='0' x2='1' y2='.45'><stop offset='.38' stop-color='#fff' stop-opacity='0'/>"
                 "<stop offset='.47' stop-color='#fff' stop-opacity='.24'/><stop offset='.52' stop-color='#fff' stop-opacity='.07'/>"
                 "<stop offset='.58' stop-color='#fff' stop-opacity='0'/></linearGradient></defs><rect width='200' height='200' fill='url(#s)'/>"),
    # lignes de balayage + un trait lumineux
    "scanner": svg("<defs><pattern id='l' width='4' height='3' patternUnits='userSpaceOnUse'><rect width='4' height='1' fill='#000' fill-opacity='.24'/></pattern></defs>"
                   "<rect width='200' height='200' fill='url(#l)'/><rect y='76' width='200' height='2.5' fill='#78fff0' fill-opacity='.6'/>"
                   "<rect y='70' width='200' height='14' fill='#78fff0' fill-opacity='.08'/>"),
    # quelques braises en bas, une lueur chaude
    "ember": svg("<defs><linearGradient id='e' x1='0' y1='1' x2='0' y2='0'><stop offset='0' stop-color='#ff6e1e' stop-opacity='.32'/>"
                 "<stop offset='.45' stop-color='#ff6e1e' stop-opacity='0'/></linearGradient></defs><rect width='200' height='200' fill='url(#e)'/>"
                 + circles(((44, 172, 2.6), (116, 160, 2.2), (156, 182, 3), (80, 140, 1.7), (132, 126, 1.4), (60, 118, 1.2)), "#ffb054", .9)),
    # un bord lumineux, sans niveau en direct : la couleur de la case, éclaircie d'un filet blanc
    "vu": svg("<rect x='3' y='3' width='194' height='194' rx='8' fill='none' stroke='currentColor' stroke-width='5'/>"
              "<rect x='3' y='3' width='194' height='194' rx='8' fill='none' stroke='#fff' stroke-opacity='.45' stroke-width='1.5'/>"
              "<rect x='10' y='10' width='180' height='180' rx='6' fill='none' stroke='#fff' stroke-opacity='.14' stroke-width='5'/>"),
    # des cercles décentrés, comme une goutte
    "ripple": svg("".join(f"<circle cx='150' cy='150' r='{r}' fill='none' stroke='#fff' stroke-opacity='{op}' stroke-width='1.6'/>"
                          for r, op in ((10, .5), (28, .34), (48, .24), (70, .16), (94, .1), (120, .06)))),
    # hachures fines en diagonale
    "rain": svg("<defs><pattern id='r' width='10' height='200' patternUnits='userSpaceOnUse' patternTransform='rotate(14)'>"
                "<rect width='1.2' height='200' fill='#fff' fill-opacity='.17'/></pattern></defs><rect width='200' height='200' fill='url(#r)'/>"),
    # deux grilles de points décalées
    "snow": svg("<defs><pattern id='a' width='16' height='16' patternUnits='userSpaceOnUse'><circle cx='4' cy='4' r='1.3' fill='#fff' fill-opacity='.5'/></pattern>"
                "<pattern id='b' width='24' height='24' patternUnits='userSpaceOnUse'><circle cx='15' cy='16' r='1' fill='#e6f0ff' fill-opacity='.3'/></pattern></defs>"
                "<rect width='200' height='200' fill='url(#a)'/><rect width='200' height='200' fill='url(#b)'/>"),
    # un éclair, et sa lueur
    "lightning": svg("<defs><radialGradient id='g' cx='.56' cy='.42' r='.45'><stop offset='0' stop-color='#c8dcff' stop-opacity='.25'/>"
                     "<stop offset='1' stop-color='#c8dcff' stop-opacity='0'/></radialGradient></defs><rect width='200' height='200' fill='url(#g)'/>"
                     "<path d='M126 -4 90 76l26 3-40 125' fill='none' stroke='#e6f0ff' stroke-opacity='.75' stroke-width='3' stroke-linejoin='round'/>"
                     "<path d='M126 -4 90 76l26 3-40 125' fill='none' stroke='#e6f0ff' stroke-opacity='.15' stroke-width='12' stroke-linejoin='round'/>"),
    # un éclat blanc qui retombe du haut
    "strobe": svg("<defs><linearGradient id='w' x1='0' y1='0' x2='0' y2='1'><stop offset='0' stop-color='#fff' stop-opacity='.5'/>"
                  "<stop offset='.45' stop-color='#fff' stop-opacity='.08'/><stop offset='.46' stop-color='#fff' stop-opacity='0'/></linearGradient></defs>"
                  "<rect width='200' height='200' fill='url(#w)'/>"),
    # l'ombre et deux yeux rouges
    "monster": svg("<defs><radialGradient id='d' cx='.5' cy='.45' r='.7'><stop offset='0' stop-color='#000' stop-opacity='0'/>"
                   "<stop offset='1' stop-color='#000' stop-opacity='.55'/></radialGradient>"
                   "<radialGradient id='y'><stop offset='0' stop-color='#ff1a1a'/><stop offset='.45' stop-color='#ff1a1a' stop-opacity='.85'/>"
                   "<stop offset='1' stop-color='#ff1a1a' stop-opacity='0'/></radialGradient></defs>"
                   "<rect width='200' height='200' fill='url(#d)'/>"
                   "<ellipse cx='80' cy='92' rx='13' ry='11' fill='url(#y)'/><ellipse cx='120' cy='92' rx='13' ry='11' fill='url(#y)'/>"),
    # des étoiles éparses
    "stars": svg(circles(((36, 44, 2), (128, 30, 1.5), (164, 96, 2.3), (72, 116, 1.5), (24, 150, 2), (144, 160, 1.7), (100, 70, 1.1), (186, 40, 1.2)),
                         "#fff", .9)
                 + "<path d='M128 22v16M120 30h16' stroke='#fff' stroke-opacity='.5' stroke-width='1'/>"),
    # deux rubans colorés croisés
    "aurora": svg("<defs><linearGradient id='a' x1='0' y1='.2' x2='1' y2='.8'><stop offset='.18' stop-color='#3cffb4' stop-opacity='0'/>"
                  "<stop offset='.36' stop-color='#3cffb4' stop-opacity='.34'/><stop offset='.52' stop-color='#5a8cff' stop-opacity='.32'/>"
                  "<stop offset='.66' stop-color='#e66eff' stop-opacity='.26'/><stop offset='.84' stop-color='#e66eff' stop-opacity='0'/></linearGradient>"
                  "<linearGradient id='b' x1='0' y1='.8' x2='1' y2='.2'><stop offset='.4' stop-color='#78ffd2' stop-opacity='0'/>"
                  "<stop offset='.55' stop-color='#78ffd2' stop-opacity='.18'/><stop offset='.7' stop-color='#78ffd2' stop-opacity='0'/></linearGradient></defs>"
                  "<rect width='200' height='200' fill='url(#a)'/><rect width='200' height='200' fill='url(#b)'/>"),
    # une lueur de feu qui monte du bas
    "fire": svg("<defs><radialGradient id='f' cx='.45' cy='1.1' r='.75'><stop offset='0' stop-color='#ff7a1e' stop-opacity='.7'/>"
                "<stop offset='.5' stop-color='#ffaa28' stop-opacity='.25'/><stop offset='1' stop-color='#ffaa28' stop-opacity='0'/></radialGradient></defs>"
                "<rect width='200' height='200' fill='url(#f)'/>"),
    # deux nuages de fumée
    "smoke": svg("<defs><radialGradient id='a'><stop offset='0' stop-color='#bec8d7' stop-opacity='.32'/><stop offset='1' stop-color='#bec8d7' stop-opacity='0'/></radialGradient>"
                 "<radialGradient id='b'><stop offset='0' stop-color='#a0afc3' stop-opacity='.26'/><stop offset='1' stop-color='#a0afc3' stop-opacity='0'/></radialGradient></defs>"
                 "<ellipse cx='62' cy='130' rx='90' ry='62' fill='url(#a)'/><ellipse cx='140' cy='80' rx='76' ry='54' fill='url(#b)'/>"),
    # une spirale à deux bras, claire
    "vortex": svg("<g transform='translate(100 100)'><path d='M0 0 L180 -40 A184 184 0 0 1 150 106 Z' fill='#fff8e0' fill-opacity='.24'/>"
                  "<path d='M0 0 L-180 40 A184 184 0 0 1 -150 -106 Z' fill='#fff8e0' fill-opacity='.16'/>"
                  "<circle r='6' fill='#fff' fill-opacity='.35'/></g>"),
    # des tranches cyan et magenta décalées
    "glitch": svg("<rect x='-8' y='46' width='190' height='16' fill='#00e5ff' fill-opacity='.26'/>"
                  "<rect x='12' y='88' width='200' height='7' fill='#00e5ff' fill-opacity='.18'/>"
                  "<rect x='-6' y='124' width='180' height='13' fill='#ff005a' fill-opacity='.24'/>"
                  "<rect x='30' y='146' width='170' height='5' fill='#ff005a' fill-opacity='.16'/>"),
}


def main():
    doc = {"_doc": "Still image of each effect of the default animation pack (docs/anim-packs.md §8). Generated by "
                   "tools/make-anim-stills.py — edit the tool, not this file.",
           "schema": 1, "stills": STILLS}
    text = json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
    if "--check" in sys.argv:
        ok = OUT.exists() and OUT.read_text() == text
        print("anim-stills.json up to date" if ok else "anim-stills.json is stale: run tools/make-anim-stills.py")
        return 0 if ok else 1
    OUT.write_text(text)
    print(f"{OUT.relative_to(OUT.parents[2])}: {len(STILLS)} stills, largest {max(len(s) for s in STILLS.values())} chars")
    return 0


if __name__ == "__main__":
    sys.exit(main())
