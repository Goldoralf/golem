#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Démarre TOUT GoleM en une commande : bridge + MIDI + Reaper (projet Set).
# L'app : http://localhost:8770/app/   (Reaper auto-charge l'OSC + le veilleur via __startup).
#   ./provision/start.sh
set -euo pipefail
# les journaux (/tmp/golem-*.log) portent noms, presets, chemins : lisibles par nous seuls (audit 2026-09-13, m2)
umask 077
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
PORT="${GOLEM_PORT:-8770}"
REAPER_BIN="${REAPER_BIN:-$HOME/opt/REAPER/reaper}"
# LE bridge de ce golem : celui de SON port. Un motif plus large tuait aussi les bridges jetables des sondes
# (check-rig-materialize, check-ui : 127.0.0.1, port libre) qui tournent à côté — mesuré le 2026-10-25.
BRIDGE_PAT="uvicorn bridge\.app:app --host [^ ]+ --port ${PORT}( |\$)"

# 1) bridge (écrit aussi le pointeur que __startup.lua lira)
if pgrep -f "$BRIDGE_PAT" >/dev/null; then
  echo "→ bridge déjà actif"
else
  [ -d .venv ] || { echo "venv absent — lance d'abord ./provision/bridge-setup.sh"; exit 1; }
  setsid nohup ./.venv/bin/uvicorn bridge.app:app --host 0.0.0.0 --port "$PORT" \
    >/tmp/golem-bridge.log 2>&1 < /dev/null &
  echo "→ bridge lancé (:$PORT)"
fi

# 2) auto-connexion MIDI (best-effort)
[ -x provision/midi-autoconnect.sh ] && ./provision/midi-autoconnect.sh >/dev/null 2>&1 || true

# 3) Reaper avec le projet Set
#
# ── REAPER CACHÉ (défaut) ────────────────────────────────────────────────────────────────
# Un utilisateur de GoleM ne lit JAMAIS Reaper : il n'a aucune raison de voir deux fenêtres
# s'ouvrir. On lance donc Reaper sur un ÉCRAN X VIRTUEL (Xvfb) — sa fenêtre existe, sur un
# écran que personne ne regarde. L'audio (PipeWire) et l'OSC n'en dépendent pas : mesuré, le
# rig se construit et sonne exactement pareil.
#
# Pourquoi Xvfb et pas « démarrer minimisé » : `wnd_state` de reaper.ini n'a AUCUN effet sous
# Linux (mesuré 2026-08-03 : 0/1/2/3 -> même fenêtre visible, SWELL ne l'honore pas), et
# Wayland interdit par conception à un programme de manipuler la fenêtre d'un autre.
#
# GOLEM_SHOW_REAPER=1 (drapeau --dev du lanceur) le remet sur l'écran réel.
# Sans Xvfb installé : on retombe sur l'écran réel EN LE DISANT — jamais d'échec muet.
REAPER_DISP=""
if [ "${GOLEM_SHOW_REAPER:-0}" != "1" ]; then
  if command -v Xvfb >/dev/null 2>&1; then
    REAPER_DISP="${GOLEM_XVFB_DISPLAY:-:99}"
    if ! xdpyinfo -display "$REAPER_DISP" >/dev/null 2>&1; then
      setsid nohup Xvfb "$REAPER_DISP" -screen 0 1920x1080x24 -nolisten tcp \
        >/dev/null 2>&1 </dev/null &
      sleep 1
    fi
  else
    echo "⚠ Xvfb absent — Reaper s'ouvrira à l'écran (sudo apt install xvfb pour le masquer)"
  fi
fi

if pgrep -x reaper >/dev/null; then
  echo "→ Reaper déjà ouvert (ouvre sets/golem-set.rpp si besoin)"
elif [ -x "$REAPER_BIN" ]; then
  # Le lecteur des captures vivantes voyage avec golem ; le poser avant le scan REAPER.
  python3 -c 'from provision.capture_player import install_bundled; install_bundled()'
  # Reaper FERMÉ : garantir la config reaper.ini (audio + OSC + activation MIDI lane Keys).
  # Sûr uniquement ici (Reaper réécrit reaper.ini à sa fermeture) → jamais si Reaper est déjà up.
  python3 provision/reaper-ini-setup.py || echo "⚠ reaper-ini-setup non appliqué (poursuite)"
  # SORTIE DE REAPER JOURNALISÉE (2026-09-07) : deux crashs en une soirée en SIGABRT (apport :
  # « signal 6 »), donc aucune ligne noyau — et le message d'abort (glibc « free(): invalid
  # pointer », assertion d'un plugin…) partait dans /dev/null. Il va désormais ici, avec l'heure
  # de chaque lancement ; on garde un fichier borné (dernier Mo) pour ne pas remplir /tmp.
  REAPER_LOG="${GOLEM_REAPER_LOG:-/tmp/golem-reaper.log}"
  if [ -f "$REAPER_LOG" ] && [ "$(stat -c %s "$REAPER_LOG" 2>/dev/null || echo 0)" -gt 1048576 ]; then
    tail -c 524288 "$REAPER_LOG" > "$REAPER_LOG.tmp" && mv "$REAPER_LOG.tmp" "$REAPER_LOG"
  fi
  echo "=== $(date '+%F %T') lancement de Reaper ($REAPER_BIN) ===" >> "$REAPER_LOG"
  # -nosplash : une fenêtre de moins, même quand Reaper est visible
  # LP_NUM_THREADS (2026-10-14) : sans carte graphique (Xvfb), l'OpenGL d'une interface de plugin est rendu par
  # llvmpipe, qui prend TOUS les cœurs — la fenêtre de Vital ouverte : ~1100 % de CPU mesurés (fils llvmpipe-0..N),
  # à côté du son. Deux fils suffisent à une interface qu'on regarde à 15 images/s (docs/plugin-window.md).
  export LP_NUM_THREADS="${GOLEM_LP_THREADS:-2}"
  # PAS DE SET = UN PROJET VIDE (2026-11-03) : sets/golem-set.rpp est de l'état local, écrit en jouant ; un golem
  # neuf n'en a pas. Le passer quand même ouvrait « There was an error opening the project » — une modale sur l'écran
  # caché, qui fige REAPER : le rappel n'était jamais lu. Même règle que provision/desktop.py (-new).
  SET="$HERE/sets/golem-set.rpp"
  if [ -f "$SET" ]; then REAPER_PROJ=("$SET"); else REAPER_PROJ=(-new); echo "→ pas encore de sets/golem-set.rpp : projet vide"; fi
  if [ -n "$REAPER_DISP" ]; then
    DISPLAY="$REAPER_DISP" setsid nohup "$REAPER_BIN" -nosplash "${REAPER_PROJ[@]}" \
      >>"$REAPER_LOG" 2>&1 < /dev/null &
    echo "→ Reaper + Set lancés (masqué sur $REAPER_DISP — golem desktop --dev pour le voir)"
  else
    setsid nohup "$REAPER_BIN" -nosplash "${REAPER_PROJ[@]}" >>"$REAPER_LOG" 2>&1 < /dev/null &
    echo "→ Reaper + Set lancés (à l'écran)"
  fi
else
  echo "⚠ Reaper introuvable ($REAPER_BIN) — ouvre-le avec sets/golem-set.rpp"
fi

IP=$(hostname -I 2>/dev/null | awk '{print $1}')
echo "✓ prêt → http://localhost:${PORT}/app/   ${IP:+· réseau http://${IP}:${PORT}/app/}"
echo "  (perf CPU live : ./provision/perf-mode.sh on)"
