#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — installer sous Linux depuis CE dossier (un clone ou une copie du dépôt) : ./install-linux.sh
# Pendant d'install-windows.cmd et d'install-macos.command (2026-11-03). Il ne télécharge pas GoleM : il passe ce
# dossier à provision/bootstrap.sh (GOLEM_SRC), qui vérifie le strict minimum (x86_64, python3…) et ouvre
# L'INSTALLATEUR GRAPHIQUE (installer/server.py → platform_linux.py) : paquets, REAPER, plugins, bridge, sons,
# commande golem et icônes. Installation SUR PLACE.
# GOLEM_INSTALLER_DRY=1 : les écrans sans rien installer (relayé par bootstrap.sh).
# Les messages s'affichent dans le terminal : en anglais (CLAUDE.md, règle 4).
set -eu
cd "$(dirname "$0")" || exit 1
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(uname -s)" = Linux ] || die "This installer is for Linux (Windows: install-windows.cmd · macOS: install-macos.command)."
# PAS sous sudo : l'installateur demande le mot de passe lui-même, à l'écran. Sous root, $USER et $HOME seraient
# ceux de root — groupe audio, ~/.vst, raccourcis posés chez root (vu sur le portable de test, 2026-11-03).
[ "$(id -u)" != 0 ] || die "Run it as yourself, without sudo: ./install-linux.sh — it asks for your password when it needs it."
[ -f provision/bootstrap.sh ] && [ -f installer/server.py ] || die "Run it from the golem folder (provision/ and installer/ are missing here)."

GOLEM_SRC="$(pwd)" exec bash provision/bootstrap.sh
