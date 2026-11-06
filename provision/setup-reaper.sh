#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Configure Reaper pour GoleM EN UNE FOIS (zéro clic ensuite) :
#  - symlinks (FXChains, Scripts/golem, OSC, __startup auto-veilleur)
#  - device OSC + carte audio dans reaper.ini (ajout si absent, backup)
# À lancer **Reaper fermé**.
#   ./provision/setup-reaper.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "→ 1/2 liens config Reaper"
"$HERE/link-reaper.sh"

echo "→ 2/2 device OSC + audio dans reaper.ini"
python3 "$HERE/reaper-ini-setup.py"

echo
echo "✓ Reaper configuré. Au prochain lancement il chargera l'OSC + le veilleur tout seul."
echo "  (SWS n'est plus requis : ./provision/plugins-sws.sh seulement pour le banc LiveConfigs)"
echo "  Et à importer ta licence Reaper (.rk) sur le rack."
