#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""L'arbre du dépôt PUBLIC (plan de lancement, étape 8) : un nouveau dépôt sans historique, fait de ce qui est commité ici
moins ce qui ne part pas — puis une passe de mots interdits sur le résultat.

    python tools/public_export.py --deny ~/golem-public/denylist.txt            # rapport seul
    python tools/public_export.py --deny ~/golem-public/denylist.txt --out DIR  # écrit l'arbre dans DIR (vide)

La liste des mots interdits vit HORS du dépôt (elle nommerait ce qu'on cache) : une expression régulière par ligne,
insensible à la casse, `#` pour un commentaire. `--allow` (même format) excuse une LIGNE entière : les mentions de
droits d'auteur, qui doivent nommer leur titulaire. Code de sortie 1 s'il reste une occurrence : la bascule ne se fait
qu'à zéro. Ne lit que l'arbre commité (`git ls-files` à HEAD) : un fichier local non commité ne part jamais."""
import argparse
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Ce qui ne part pas (chemins commités) : notes privées et archives, maquettes (faites avec les données réelles du
# propriétaire), instantanés de ses presets dans les tests
EXCLUDE = (
    "docs/private/",
    "docs/archive/",
    "mockups/",
)


def tracked():
    out = subprocess.check_output(["git", "-C", ROOT, "ls-files", "-z"])
    return [p for p in out.decode().split("\0") if p]


def kept(paths):
    return [p for p in paths if not p.startswith(EXCLUDE) and os.path.isfile(os.path.join(ROOT, p))]


def load_deny(path):
    pats = []
    for ln in open(os.path.expanduser(path), encoding="utf-8"):
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            pats.append((ln, re.compile(ln, re.I)))
    return pats


def scan(paths, pats, allow=()):
    """[(motif, chemin, n° de ligne, extrait)] — le nom du fichier compte aussi ; une ligne excusée par `allow` non."""
    hits = []
    for p in paths:
        for src, rx in pats:
            if rx.search(p):
                hits.append((src, p, 0, "(file name)"))
        try:
            with open(os.path.join(ROOT, p), encoding="utf-8") as f:
                for n, ln in enumerate(f, 1):
                    if any(rx.search(ln) for _, rx in allow):
                        continue
                    for src, rx in pats:
                        m = rx.search(ln)
                        if m:
                            a = max(0, m.start() - 40)
                            hits.append((src, p, n, ln[a:m.end() + 40].strip()))
        except (UnicodeDecodeError, OSError):
            continue                                   # binaire : seul le nom compte
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--deny", required=True, help="denylist file (outside the repository)")
    ap.add_argument("--allow", help="lines excused (copyright notices), same format")
    ap.add_argument("--out", help="write the public tree into this empty directory")
    ap.add_argument("--summary", action="store_true", help="counts per pattern and per file only")
    a = ap.parse_args()
    paths = kept(tracked())
    hits = scan(paths, load_deny(a.deny), load_deny(a.allow) if a.allow else ())
    if a.summary:
        per = {}
        for src, p, _, _ in hits:
            per.setdefault(src, {}).setdefault(p, 0)
            per[src][p] += 1
        for src, files in sorted(per.items(), key=lambda kv: -sum(kv[1].values())):
            print(f"{src}: {sum(files.values())} in {len(files)} files")
            for p, c in sorted(files.items(), key=lambda kv: -kv[1])[:8]:
                print(f"    {c:4d}  {p}")
    else:
        for src, p, n, ex in hits:
            print(f"{p}:{n}: [{src}] {ex}")
    print(f"{len(paths)} files kept, {len(hits)} forbidden occurrences", file=sys.stderr)
    if a.out:
        if os.path.exists(a.out) and os.listdir(a.out):
            sys.exit(f"{a.out} is not empty")
        for p in paths:
            dst = os.path.join(a.out, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(os.path.join(ROOT, p), dst)
    sys.exit(1 if hits else 0)


if __name__ == "__main__":
    main()
