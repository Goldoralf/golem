#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Installe des grilles À LA PLACE d'une synchro golem.fm — pour travailler en attendant.

    ./tools/seed-standards.py                       # le petit jeu par défaut (6 grilles, 6 styles)
    ./tools/seed-standards.py "Blue Bossa" "So What"
    ./tools/seed-standards.py --list autumn          # cherche dans le corpus amont
    ./tools/seed-standards.py --clear                # vide le dossier synchronisé

⚠ CE N'EST PAS UN CATALOGUE. Le rack ne connaît pas de liste de standards : il **reçoit**
ce que golem.fm lui synchronise (`docs/standards.md`, Addendum 3). Cet outil existe pour
une seule raison — l'endpoint `GET /api/ext/standards` n'est pas encore livré côté
golem.fm, et on ne va pas attendre pour jouer.

Chaque grille posée est marquée `seeded: true` dans son enveloppe `_golem` : l'UI l'affiche
comme telle, et **la première vraie synchro les remplacera** (le miroir efface ce qui n'est
pas tagué). C'est voulu : rien ici ne doit survivre en douce à l'arrivée du vrai canal.

La source est le dataset amont (mikeoliphant/JazzStandards), téléchargé au besoin dans
`library/standards/jazz-standards.json` — un fichier de travail, hors Git, que le produit
ne lit jamais.
"""
import argparse
import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge import standards as S            # noqa: E402

UPSTREAM = "https://raw.githubusercontent.com/mikeoliphant/JazzStandards/master/JazzStandards.json"

# six styles différents : de quoi éprouver la grammaire, le comping et la transposition
DEFAULT = ["Autumn Leaves", "Blue Bossa", "So What", "All The Things You Are",
           "Take The A Train", "Body And Soul"]


def corpus():
    """Le dataset amont, téléchargé si absent. Fichier de TRAVAIL, jamais lu par le produit."""
    if not os.path.exists(S.STD_FILE):
        os.makedirs(S.STD_DIR, exist_ok=True)
        print(f"  ↓ dataset amont (~900 kB) — {UPSTREAM}")
        with urllib.request.urlopen(UPSTREAM, timeout=60) as r:
            blob = r.read()
        d = json.loads(blob)
        if not (isinstance(d, list) and len(d) > 500 and "Sections" in d[0]):
            print("  ✗ ce n'est pas le dataset attendu — rien écrit")
            sys.exit(1)
        tmp = S.STD_FILE + ".tmp"
        with open(tmp, "wb") as f:
            f.write(blob)
        os.replace(tmp, S.STD_FILE)
    with open(S.STD_FILE, encoding="utf-8") as f:
        return json.load(f)


def install(raw, slug):
    raw = dict(raw)
    raw["_golem"] = {"slug": slug, "synced_at": None, "source": "seed (tools/seed-standards.py)",
                     "seeded": True}
    os.makedirs(S.SYNCED_DIR, exist_ok=True)
    p = os.path.join(S.SYNCED_DIR, slug + ".json")
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(raw, f, ensure_ascii=False)
    os.replace(tmp, p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("titles", nargs="*", help="titres à installer (défaut : un jeu de 6)")
    ap.add_argument("--list", metavar="MOTIF", help="cherche dans le corpus amont, n'installe rien")
    ap.add_argument("--clear", action="store_true", help="vide le dossier synchronisé")
    a = ap.parse_args()

    if a.clear:
        n = 0
        for fn in os.listdir(S.SYNCED_DIR) if os.path.isdir(S.SYNCED_DIR) else []:
            if fn.endswith(".json"):
                os.remove(os.path.join(S.SYNCED_DIR, fn))
                n += 1
        S.invalidate()
        print(f"  {n} grille(s) retirée(s).")
        return 0

    raw = corpus()
    if a.list:
        q = a.list.lower()
        hits = [r for r in raw if q in (r.get("Title") or "").lower()
                or q in (r.get("Composer") or "").lower()]
        for r in hits[:40]:
            print(f"  {r['Title']:<44} {r.get('Composer') or '—':<24} {r.get('Rhythm')}")
        print(f"  — {len(hits)} résultat(s)")
        return 0

    want = a.titles or DEFAULT
    by_title = {(r.get("Title") or "").lower(): r for r in raw}
    ok, miss = [], []
    for t in want:
        r = by_title.get(t.lower())
        if not r:
            miss.append(t)
            continue
        slug = S.slugify(r["Title"])
        install(r, slug)
        ok.append((slug, r["Title"]))
    S.invalidate()

    for slug, title in ok:
        print(f"  ✓ {title}  ({slug})")
    for t in miss:
        print(f"  ✗ introuvable : {t}   (essaie --list)")
    print(f"\n  {len(ok)} grille(s) posée(s) dans library/standards/synced/.")
    print("  Elles sont marquées « seeded » : la première VRAIE synchro golem.fm les remplacera.")
    return 1 if miss else 0


if __name__ == "__main__":
    sys.exit(main())
