#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Auto-connexion MIDI au boot : FCB1010 → Reaper, Reaper → Whammy (via Volt 276 MIDI 1).
# Sur Linux/ALSA, Reaper s'abonne lui-même au port "Volt 276 MIDI 1" (config dans Reaper).
# Ce script est un FILET pour le mode headless : il s'assure que le port existe et le log.
#
# Pour le rack final : à lancer via systemd --user après pipewire, avant l'autostart Reaper.
set -euo pipefail
PORT="Volt 276 MIDI 1"

echo "Ports MIDI séquenceur disponibles :"
aconnect -l || true

if aconnect -l | grep -q "$PORT"; then
  echo "✓ '$PORT' présent (FCB en in / Whammy en out passent par là)."
else
  echo "✗ '$PORT' absent — la Volt est-elle allumée et branchée en USB ?"
  exit 1
fi

# Note : les abonnements ALSA réels (FCB↔Reaper↔Whammy) se font côté Reaper
# (Preferences/MIDI Devices : activer le port en entrée ET en sortie).
# Si un jour on route hors Reaper, ajouter ici les `aconnect <src> <dst>` voulus.
