# SPDX-License-Identifier: GPL-3.0-or-later
"""L'ÉTAT LOCAL d'un rack, sorti du dépôt le 2026-10-15 (audit, lot 4 ; CLAUDE.md règle 2).

Ces fichiers étaient SUIVIS par git alors que le bridge les réécrit en tournant (réglages Rec/Click/Compo, cartes
rencontrées, rôles des entrées, setlists). Un changement de version d'avant cette date vers après les SUPPRIME
(`git checkout`/`git pull` retire un fichier qui sort du dépôt) — ou refuse de basculer s'il est modifié. `preserve`
les met de côté avant le changement et les rend après : la mise à jour intégrée (/api/system/update) l'appelle, et
`tools/local-state.py` fait la même chose autour d'un `git pull` à la main. Sans fichier suivi concerné, ne fait rien."""
import os
import shutil
import subprocess
import tempfile

from . import config as C

# Les chemins du dépôt qui sont de l'état local (dossiers terminés par « / »). Miroir de la section « ÉTAT LOCAL DU
# RACK » de .gitignore.
PATHS = ("config/click.json", "config/compo.json", "config/recorder.json", "config/io.json", "config/cards/",
         "config/inputmaps/", "setlists/")


def _git(*args):
    return subprocess.run(["git", "-C", C.ROOT, *args], capture_output=True, text=True, timeout=30)


def tracked():
    """Les fichiers d'état local encore SUIVIS dans le HEAD courant (une version d'avant le 2026-10-15)."""
    r = _git("ls-files", "--", *PATHS)
    return [p for p in r.stdout.splitlines() if p] if r.returncode == 0 else []


def preserve():
    """Met de côté l'état local suivi et le remet à la version du dépôt (pour que la bascule passe). Rend une
    fonction `restore()` à appeler APRÈS la bascule — elle remet chaque fichier tel qu'il était sur la machine."""
    files = [p for p in tracked() if os.path.isfile(os.path.join(C.ROOT, p))]
    if not files:
        return lambda: []
    keep = tempfile.mkdtemp(prefix="golem-local-state-")
    for p in files:
        dst = os.path.join(keep, p)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(os.path.join(C.ROOT, p), dst)
    _git("checkout", "--", *files)                        # versions du dépôt : `git checkout <tag>` ne refuse plus

    def restore():
        back = []
        for p in files:
            src, dst = os.path.join(keep, p), os.path.join(C.ROOT, p)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.copy2(src, dst)
            back.append(p)
        shutil.rmtree(keep, ignore_errors=True)
        return back
    return restore
