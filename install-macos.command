#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — installer sous macOS depuis CE dossier (un clone ou une copie du dépôt) : double-clic dans le
# Finder. Pendant d'install-windows.cmd (docs/integration-macos.md). Il ne télécharge pas GoleM : il
# trouve un Python 3.12+ et ouvre L'INSTALLATEUR GRAPHIQUE (installer/server.py -> platform_macos.py),
# qui pose REAPER, les plugins, le bridge et les apps GoleM. Lancé depuis un clone : installation SUR PLACE.
# GOLEM_INSTALLER_DRY=1 : les écrans sans rien installer.
# Les messages s'affichent dans Terminal : en anglais (CLAUDE.md, règle 4).
cd "$(dirname "$0")" || exit 1
say() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; printf 'Press Return to close.'; read -r _; exit 1; }

[ "$(uname -s)" = Darwin ] || die "This installer is for macOS."
[ "$(uname -m)" = arm64 ] || say "⚠ GoleM targets Apple Silicon Macs — this one is $(uname -m); it may work, untested."

# 3.12 ou 3.13 SEULEMENT : onnxruntime 1.23.2 (le lock du bridge sous macOS) n'a pas de wheel au-delà, et
# `python3` pointe sur le dernier Python posé (3.15 sur le Mac de test, 2026-11-04 : l'étape bridge échouait).
PY=""
for c in python3.13 python3.12 /Library/Frameworks/Python.framework/Versions/3.13/bin/python3 \
         /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 python3; do
  p=$(command -v "$c" 2>/dev/null) || continue
  if "$p" -c 'import sys; sys.exit(0 if (3, 12) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null; then PY="$p"; break; fi
done
[ -n "$PY" ] || die "Python 3.12 or 3.13 is required (3.14 and later lack a package golem needs): install Python 3.13 from https://www.python.org/downloads/macos/ — it can sit next to a newer one — then double-click this file again."
say "Python: $PY ($("$PY" -c 'import platform; print(platform.python_version())'))"

# le Python de python.org n'a pas de certificats tant que son « Install Certificates » n'a pas tourné :
# le magasin du système sert aux téléchargements HTTPS de l'installateur (bridge/config.py fait pareil)
[ -n "${SSL_CERT_FILE:-}" ] || [ ! -f /etc/ssl/cert.pem ] || export SSL_CERT_FILE=/etc/ssl/cert.pem
say "Opening the GoleM installer — keep this window open until it finishes"
exec "$PY" installer/server.py --src "$(pwd)" --open ${GOLEM_INSTALLER_DRY:+--dry}
