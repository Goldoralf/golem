#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Un `git pull` à la main SANS perdre l'état local du rack (bridge/local_state.py, audit 2026-10-15).

    ./tools/local-state.py pull          # met de côté, git pull --ff-only, remet

Le passage d'une version d'avant le 2026-10-15 à une version d'après supprime config/click.json, config/recorder.json,
config/cards/, config/inputmaps/… (ils sortent du dépôt). Une fois passé, un `git pull` normal suffit."""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bridge import local_state  # noqa: E402


def main():
    if sys.argv[1:] != ["pull"]:
        print(__doc__)
        return 2
    print("état local encore suivi :", ", ".join(local_state.tracked()) or "aucun")
    restore = local_state.preserve()
    r = subprocess.run(["git", "-C", local_state.C.ROOT, "pull", "--ff-only"])
    back = restore()
    print(("remis : " + ", ".join(back)) if back else "rien à remettre")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
