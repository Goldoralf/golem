#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Envoi d'une commande BRUTE au veilleur Reaper — contrat presets/.command.json (écriture atomique
+ nonce `seq`, exactement comme bridge/commands.py::write_command).

Sert aux actions de golem_apply qui n'ont PAS d'endpoint bridge (dev tools) :

    python3 reaper/golem-cmd.py '{"action":"midilist"}'                  # -> répertoire runtime/golem-midilist.json
    python3 reaper/golem-cmd.py '{"action":"reload","script":"golem_midi"}'   # hot-swap d'une boucle defer
    python3 reaper/golem-cmd.py '{"action":"recdiag","tag":""}'          # -> presets/.recdiag.json

(le bridge doit tourner ou non : peu importe, c'est golem_watch dans Reaper qui lit le fichier.)"""
import os, json, sys
ROOT = os.environ.get("GOLEM_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from bridge.commands import write_command  # noqa: E402
cmd = json.loads(sys.argv[1])
cmd["seq"] = write_command(cmd)
print("sent:", cmd)
