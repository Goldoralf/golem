#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Passe le CPU en mode 'performance' (gouverneur) pour l'audio temps-réel.
# Sans ça : CPU en powersave → fréquence basse → xruns quand les chaînes neurales chargent.
#
#   ./provision/perf-mode.sh on    # performance (live / jeu)
#   ./provision/perf-mode.sh off   # powersave (repos / batterie)
#   ./provision/perf-mode.sh       # affiche l'état
set -euo pipefail
GOV_FILES=(/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_governor)

state() { cat "${GOV_FILES[0]}" 2>/dev/null; }
# écrit en root : direct si déjà root (lancé par le bridge via sudo NOPASSWD), sinon via sudo (usage manuel)
run() { if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi; }

case "${1:-status}" in
  on)  echo "→ performance"; for f in "${GOV_FILES[@]}"; do echo performance | run tee "$f" >/dev/null; done ;;
  off) echo "→ powersave";   for f in "${GOV_FILES[@]}"; do echo powersave   | run tee "$f" >/dev/null; done ;;
  status) ;;
  *) echo "usage: $0 [on|off|status]"; exit 1 ;;
esac
echo "Gouverneur actuel : $(state)"
echo "Fréquence cpu0 : $(awk '{printf "%.2f GHz\n", $1/1e6}' /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq)"
# NB: réinitialisé au reboot. Pour le rack : rendre permanent (systemd/tuned). Voir system-tuning.md
