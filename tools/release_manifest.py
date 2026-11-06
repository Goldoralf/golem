#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""SHA256SUMS d'une release (docs/release-signing.md §5) : l'empreinte de chaque fichier du tag, tel que `git archive` le
livre — donc tel que l'archive de GitHub le contient. Puis la signature avec la clé des tags :

    tools/release_manifest.py v0.6.2 --out /tmp/rel          # écrit /tmp/rel/SHA256SUMS
    ssh-keygen -Y sign -f ~/.ssh/golem_release.pub -n git /tmp/rel/SHA256SUMS   # → SHA256SUMS.sig (clé dans l'agent)

Les deux fichiers sont joints à la release GitHub ; la mise à jour par archive et le bootstrap sans git les vérifient."""
import argparse
import hashlib
import io
import os
import subprocess
import sys
import tarfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def manifest(tag, root=ROOT):
    data = subprocess.run(["git", "-C", root, "archive", "--format=tar", tag], capture_output=True, check=True).stdout
    lines = []
    with tarfile.open(fileobj=io.BytesIO(data)) as t:
        for m in t.getmembers():
            if m.isfile():
                lines.append(f"{hashlib.sha256(t.extractfile(m).read()).hexdigest()}  {m.name}")
    return "\n".join(sorted(lines, key=lambda ln: ln.split("  ", 1)[1])) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("tag")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    os.makedirs(a.out, exist_ok=True)
    text = manifest(a.tag)
    with open(os.path.join(a.out, "SHA256SUMS"), "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"{a.out}/SHA256SUMS : {text.count(chr(10))} files of {a.tag}")


if __name__ == "__main__":
    sys.exit(main())
