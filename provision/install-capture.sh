#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Le même lecteur que sur desktop, intégré à l'installation du rack.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
python3 "$HERE/capture_player.py"
