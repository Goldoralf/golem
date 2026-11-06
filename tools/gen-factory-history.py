#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""L'HISTORIQUE DE L'USINE (docs/factory.md §2) : chaque version qu'un commit a livrée de chaque fichier de
library/factory/, en sha256 aux fins de ligne normalisées — `library/factory/history.json`.

Le bridge s'en sert à la pose (bridge/factory.py `seed`) : un objet posé qui est une ANCIENNE version intacte est
remplacé par la courante ; une retouche ne bouge pas. Sans ce fichier, un golem ne saurait pas distinguer « jamais
touché, juste vieux » de « retouché par la personne » — une release n'a pas de Git.

À relancer après toute modification de library/factory/ (tests/test_factory.py échoue sinon) :

    python tools/gen-factory-history.py

Le fichier est ajouté à l'historique, jamais réduit : une version déjà livrée reste reconnue."""
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bridge import factory as F  # noqa: E402

OUT = os.path.join(ROOT, "library", "factory", "history.json")


def _sha(data):
    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def _git(*args, binary=False):
    r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=False)
    return r.stdout if binary else r.stdout.decode("utf-8", "replace")


def main():
    try:
        with open(OUT, encoding="utf-8") as f:
            hist = {k: list(v) for k, v in json.load(f).items() if not k.startswith("_")}
    except (OSError, ValueError):
        hist = {}
    for _kind, (sub, _dst, ext) in F.KINDS.items():
        d = os.path.join(F.SRC, sub)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if not fn.endswith(ext) or fn.startswith("."):
                continue
            rel = f"library/factory/{sub}/{fn}"
            shas = hist.setdefault(f"{sub}/{fn}", [])
            # l'empreinte CANONIQUE (sans ce que la machine écrit : factory.canon_sha) de chaque version JSON
            canon = hist.setdefault(f"canon:{sub}/{fn}", []) if ext == ".json" else None

            def add(blob):
                if _sha(blob) not in shas:
                    shas.append(_sha(blob))
                c = F.canon_sha(blob, ext) if canon is not None else None
                if c and c not in canon:
                    canon.append(c)

            for commit in reversed(_git("log", "--format=%H", "--follow", "--", rel).split()):
                for path in (rel,) + tuple(p for p in _git("show", "--name-only", "--format=", commit).split()
                                           if p.endswith("/" + fn) and p != rel):
                    blob = _git("show", f"{commit}:{path}", binary=True)
                    if blob:
                        add(blob)
            with open(os.path.join(d, fn), "rb") as f:          # la version de l'arbre (pas encore commitée)
                add(f.read())
    out = {"_comment": "Every version of every factory file a commit has shipped (sha256, CRLF normalised); "
                       "`canon:` keys hold the same versions without what a machine writes (factory.canon_sha). "
                       "Written by tools/gen-factory-history.py; read by bridge/factory.py seed(). Never shrink it."}
    out.update(sorted(hist.items()))
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(out, f, indent=1)
        f.write("\n")
    n = [k for k in hist if not k.startswith("canon:")]
    print(f"{OUT}: {len(n)} files, {sum(len(hist[k]) for k in n)} versions")


if __name__ == "__main__":
    main()
