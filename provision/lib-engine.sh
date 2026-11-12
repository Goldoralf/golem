# SPDX-License-Identifier: GPL-3.0-or-later
# Le MOTEUR AUDIO choisi, pour les scripts du lanceur (start.sh, golem stop/status) — docs/ardour-plan.md §7c, lot A2.1.
# Le choix vit dans config/engine.json (bridge/engines.py, seul lecteur) ; GOLEM_ENGINE le force (DEV seulement, comme
# côté bridge : bridge/engine/__init__.py). REAPER garde ses fonctions dans lib-reaper.sh ; ici, ce qui dépend du moteur.

# l'id du moteur choisi : reaper (défaut) ou ardour (le Golem Engine)
golem_engine() {
  local here="${1:?racine golem}"
  if [ -n "${GOLEM_ENGINE:-}" ]; then echo "$GOLEM_ENGINE"; return; fi
  python3 -c "import sys; sys.path.insert(0, sys.argv[1]); from bridge import engines; print(engines.current(root=sys.argv[1]) or 'reaper')" \
    "$here" 2>/dev/null || echo reaper
}

# le PID du Golem Engine de CE golem (presets/.engine.pid, écrit par golem-engine/golem/engine/run.sh), s'il vit
golem_engine_pid() {
  local here="${1:?racine golem}" p
  p=$(cat "$here/presets/.engine.pid" 2>/dev/null) || return 0
  [ -n "$p" ] && [ -r "/proc/$p/cmdline" ] || return 0
  [ "$(awk '{print $3}' "/proc/$p/stat" 2>/dev/null)" = Z ] && return 0
  tr '\0' '\n' < "/proc/$p/cmdline" | head -2 | grep -q 'luasession$' && echo "$p"
}

# lance le Golem Engine (session, backend, carte : GOLEM_ENGINE_SESSION / _BACKEND / _DEVICE), journal /tmp/golem-engine.log
start_golem_engine() {
  local here="${1:?racine golem}"
  local dir="${GOLEM_ENGINE_DIR:-$HOME/golem-engine}"
  # la session vit DANS golem (sets/, état local comme sets/golem-set.rpp) : rien hors de l'install, rien à noter au reçu
  local session="${GOLEM_ENGINE_SESSION:-$here/sets/golem-engine}"
  local log="${GOLEM_ENGINE_LOG:-/tmp/golem-engine.log}"
  if [ -n "$(golem_engine_pid "$here")" ]; then echo "→ Golem Engine déjà ouvert"; return 0; fi
  if [ ! -x "$dir/golem/engine/run.sh" ]; then echo "⚠ Golem Engine introuvable ($dir/golem/engine/run.sh)"; return 1; fi
  echo "=== $(date '+%F %T') lancement du Golem Engine ($dir) ===" >> "$log"
  # la carte ACTIVE de golem en ALSA (bridge/engine/ardour.py card_device) ; sans carte connue : le pilote factice
  local device="${GOLEM_ENGINE_DEVICE-$(python3 -c "import sys; sys.path.insert(0, sys.argv[1]); from bridge.engine.ardour import card_device; print(card_device() or '')" "$here" 2>/dev/null)}"
  local backend="${GOLEM_ENGINE_BACKEND:-$([ -n "$device" ] && echo ALSA || echo "None (Dummy)")}"
  setsid nohup bash "$dir/golem/engine/run.sh" "$here" "$session" "$backend" "$device" >>"$log" 2>&1 < /dev/null &
  echo "→ Golem Engine lancé (journal $log)"
}

# arrête le Golem Engine de ce golem et attend sa mort réelle — 10 s au plus
stop_golem_engine() {
  local here="${1:?racine golem}" p i
  p=$(golem_engine_pid "$here")
  [ -n "$p" ] || return 0
  kill "$p" 2>/dev/null || true
  for i in $(seq 1 50); do [ -z "$(golem_engine_pid "$here")" ] && return 0; sleep 0.2; done
  echo "⚠ le Golem Engine ne s'est pas arrêté en 10 s"
  return 1
}
