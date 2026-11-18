#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Reprend le téléchargement des captures d'usine (TONE3000) hors de golem : le ↻ Try again de l'installateur quand
# certaines ont échoué (provision/install.sh, bridge/factory_fetch.py). Rien n'est écrit hors du dossier de golem.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE/.."
exec .venv/bin/python -m bridge.factory_fetch
