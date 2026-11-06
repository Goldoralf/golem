#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Prépare l'environnement Python du bridge GoleM (venv + dépendances).
#   ./provision/bridge-setup.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"

if [ ! -d .venv ]; then
  echo "→ création du venv .venv"
  python3 -m venv .venv
fi
# le VERROU, empreintes comprises (audit 2026-10-15) : chaque paquet, dépendances indirectes incluses, à la version et
# au fichier près — un paquet modifié sur l'index est refusé. Régénérer après avoir changé requirements.txt :
#   uv pip compile --universal --generate-hashes --python-version 3.12 bridge/requirements.txt -o bridge/requirements.lock
echo "→ installation des dépendances (bridge/requirements.lock, empreintes vérifiées)"
./.venv/bin/pip install -q --disable-pip-version-check --require-hashes -r bridge/requirements.lock
echo "✓ bridge prêt. Lancer : ./provision/serve-rig.sh"
