#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installe l'extension SWS pour Reaper — OPTIONNELLE depuis le 2026-09-22 : le moteur de scènes est
# golem_rig, LiveConfigs n'a jamais servi, et la destination d'un send se lit nativement
# (P_DESTTRACK). Utile pour le banc tools/bench-liveconfigs.py et le diagnostic MIDI étendu.
# Non-portable install : extraction dans ~/.config/REAPER. Aucun sudo.
#   ./provision/plugins-sws.sh
set -euo pipefail

DEST="$HOME/.config/REAPER"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-fetch.sh"      # fetch_verified : empreintes épinglées
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"    # reçu d'install (docs/uninstall.md §2)

# Version ÉPINGLÉE et vérifiée (audit 2026-10-15) : c'était « la dernière » de l'API GitHub, sans contrôle. La même que
# provision/install-plugins.sh. Monter = changer SWS_VER et ajouter la ligne de provision/downloads.sha256.
SWS_VER="v2.14.0.7"
URL="https://github.com/reaper-oss/sws/releases/download/$SWS_VER/reaper_sws-x86_64.so"
echo "→ SWS $SWS_VER : $URL"
mkdir -p "$DEST/UserPlugins"
ex=$(receipt_existed "$DEST/UserPlugins/reaper_sws-x86_64.so")
fetch_verified "$URL" "$DEST/UserPlugins/reaper_sws-x86_64.so" || exit 1
# shellcheck disable=SC2086
receipt_add "$DEST/UserPlugins/reaper_sws-x86_64.so" file plugins $ex

if ls "$DEST"/UserPlugins/reaper_sws*.so >/dev/null 2>&1; then
  echo "✓ SWS installé : $(ls "$DEST"/UserPlugins/reaper_sws*.so)"
  echo "  Relance Reaper → menu Extensions doit apparaître. LiveConfigs : Extensions → Live Configs."
else
  echo "⚠ extraction faite mais reaper_sws*.so non trouvé dans UserPlugins/ — vérifie l'archive."
fi
