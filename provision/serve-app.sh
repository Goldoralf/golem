#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Sert l'app GoleM en local. Accessible depuis l'écran tactile du rack ET le téléphone (LAN).
# L'app lit library/catalog/tones-index.json -> on sert la RACINE du repo.
#
#   ./provision/serve-app.sh          # port 8770
#   ./provision/serve-app.sh 9000     # port custom
set -euo pipefail
PORT="${1:-8770}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "→ GoleM — bibliothèque"
echo "   local   : http://localhost:${PORT}/app/"
[ -n "$IP" ] && echo "   réseau  : http://${IP}:${PORT}/app/   (téléphone sur le même Wi-Fi)"
echo "   Ctrl-C pour arrêter."
exec python3 -m http.server "$PORT" --bind 0.0.0.0
