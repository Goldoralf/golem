#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Coupe TOUT GoleM proprement : bridge (uvicorn) + Reaper.
# Miroir de provision/start.sh.  ->  ./provision/stop.sh
set -uo pipefail

# arrêt gracieux (SIGTERM) puis SIGKILL si récalcitrant.
_kill() {  # $1 = libellé ; $2 = flag pgrep (-f | -x) ; $3 = motif
  local label="$1" flag="$2" pat="$3"
  if ! pgrep "$flag" "$pat" >/dev/null 2>&1; then echo "→ $label : déjà arrêté"; return; fi
  echo "→ $label : arrêt…"
  pkill "$flag" "$pat" 2>/dev/null || true
  for _ in $(seq 1 12); do
    pgrep "$flag" "$pat" >/dev/null 2>&1 || { echo "  ✓ $label arrêté"; return; }
    sleep 0.3
  done
  echo "  ⚠ $label récalcitrant → SIGKILL"; pkill -9 "$flag" "$pat" 2>/dev/null || true
}

PORT="${GOLEM_PORT:-8770}"
# LE bridge de ce golem : celui de SON port. Un motif plus large tuait aussi les bridges jetables des sondes
# (check-rig-materialize, check-ui : 127.0.0.1, port libre) qui tournent à côté — mesuré le 2026-10-25.
BRIDGE_PAT="uvicorn bridge\.app:app --host [^ ]+ --port ${PORT}( |\$)"
_kill "bridge" -f "$BRIDGE_PAT"
_kill "Reaper" -x "reaper"
echo "✓ GoleM arrêté."
