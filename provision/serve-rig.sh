#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Lance le bridge GoleM (app + API + OSC vers Reaper).
# Accessible depuis l'écran tactile du rack ET le téléphone (LAN).
#   ./provision/serve-rig.sh [port]
set -euo pipefail
PORT="${1:-8770}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

# Config machine-locale (GOLEM_RECALL_ACTION = command ID du ReaScript apply, etc.)
if [ -f .env ]; then set -a; . ./.env; set +a; fi

[ -d .venv ] || { echo "venv absent — lance d'abord ./provision/bridge-setup.sh"; exit 1; }

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "→ GoleM — bridge & cockpit"
echo "   Live    : http://localhost:${PORT}/app/"
echo "   Library : http://localhost:${PORT}/app/"
[ -n "$IP" ] && echo "   réseau  : http://${IP}:${PORT}/app/   (téléphone, même Wi-Fi)"
echo "   OSC     : Reaper écoute :8000  ·  bridge écoute :9000  (cf. reaper/OSC/golem.ReaperOSC)"
echo "   Ctrl-C pour arrêter."
exec ./.venv/bin/uvicorn bridge.app:app --host 0.0.0.0 --port "$PORT"
