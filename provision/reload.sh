#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
umask 077   # journaux lisibles par nous seuls (audit 2026-09-13, m2)
# Recharge le BRIDGE après une modif Python — SANS toucher à Reaper.
# (Reaper garde son veilleur golem_watch, qui relit le Lua tout seul à chaque commande.)
# = tue l'uvicorn bridge puis relance via start.sh (qui saute Reaper s'il tourne déjà).
#   ->  ./provision/reload.sh
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
PORT="${GOLEM_PORT:-8770}"
# LE bridge de ce golem : celui de SON port. Un motif plus large tuait aussi les bridges jetables des sondes
# (check-rig-materialize, check-ui : 127.0.0.1, port libre) qui tournent à côté — mesuré le 2026-10-25.
BRIDGE_PAT="uvicorn bridge\.app:app --host [^ ]+ --port ${PORT}( |\$)"

if pgrep -f "$BRIDGE_PAT" >/dev/null 2>&1; then
  echo "→ bridge : arrêt…"
  pkill -f "$BRIDGE_PAT" 2>/dev/null || true
  for _ in $(seq 1 12); do pgrep -f "$BRIDGE_PAT" >/dev/null 2>&1 || break; sleep 0.3; done
  pkill -9 -f "$BRIDGE_PAT" 2>/dev/null || true
else
  echo "→ bridge : pas actif"
fi

# aseqdump orphelins d'anciens bridges (pré-PDEATHSIG) : on nettoie avant de relancer
pkill -x aseqdump 2>/dev/null || true   # -x = nom exact (pas la cmdline : évite de tuer un shell qui la cite)

# --with-reaper (la mise à jour depuis System ▸ About, 2026-11-06) : REAPER aussi, pour qu'il charge les scripts Lua et
# les JSFX de la nouvelle version — start.sh le relance, puisqu'il n'y en a plus
# Sans l'option : REAPER aussi quand ses scripts ont changé depuis son lancement (reaper_scripts_stale) — c'est le cas
# d'une mise à jour lancée par une version d'avant, qui ne passe pas --with-reaper.
. "$HERE/provision/lib-reaper.sh"
if [ -n "$(rack_reaper_pids)" ] && { [ "${1:-}" = "--with-reaper" ] || reaper_scripts_stale "$HERE"; }; then
  echo "→ Reaper : arrêt (ses scripts ont changé)…"
  stop_rack_reaper || true
fi

echo "→ bridge : relance via start.sh"
exec ./provision/start.sh
