# SPDX-License-Identifier: GPL-3.0-or-later
"""os.replace qui survit à Windows.

⚠ WINDOWS : os.replace échoue (PermissionError) tant qu'un AUTRE processus ou thread a la cible ouverte
— Python ne l'ouvre pas en partage de suppression, REAPER non plus. Une lecture dure quelques ms : on
réessaie brièvement, et un échec final ne laisse pas de fichier temporaire derrière lui.

Mesuré deux fois le 2026-10-03 : devices.json réécrit pendant que l'écran le lisait (écriture perdue, la
veille des branchements tuée), puis la fente de commande .command.json pendant que golem_watch la lisait —
la commande partait en exception et n'atteignait jamais REAPER.
"""
import os
import time

TRIES = 25
PAUSE = 0.02


def replace(tmp, path):
    for attempt in range(TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if os.name != "nt" or attempt == TRIES - 1:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise
            time.sleep(PAUSE)
