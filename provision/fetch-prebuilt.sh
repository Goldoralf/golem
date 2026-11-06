#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Pose un plugin PRÉCOMPILÉ (dépôt public Goldoralf/golem-binaries, release épinglée) au lieu de le compiler : ~10 min
# de moins par installation, et plus de dépendance à gitlab.com (Eigen, 2 installs VM sur 3 mortes le 2026-10-23).
# Lancé CHEZ L'UTILISATEUR par les scripts install-*.sh ; rend 1 si le binaire n'a pas pu être posé — le script
# appelant compile alors les mêmes commits, comme avant. GOLEM_BUILD_FROM_SOURCE=1 force la compilation.
#
#   fetch-prebuilt.sh <asset> <dossier de destination> <nom du bundle>
#   ex. fetch-prebuilt.sh neural_amp_modeler.lv2 ~/.lv2 neural_amp_modeler.lv2
#
# L'archive est épinglée dans downloads.sha256 (fetch_verified) : une release republiée sous le même nom avec un
# autre contenu est refusée. Monter de version = nouvelle release linux-plugins-vN + ses lignes dans downloads.sha256.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
. "$HERE/lib-fetch.sh"
GOLEM_PREBUILT_BASE="${GOLEM_PREBUILT_BASE:-https://github.com/Goldoralf/golem-binaries/releases/download/linux-plugins-v2}"
asset="$1" dest="$2" bundle="$3"
[ "${GOLEM_BUILD_FROM_SOURCE:-0}" = 1 ] && { echo "  → GOLEM_BUILD_FROM_SOURCE=1 : compilation depuis la source"; exit 1; }
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
echo "  ↓ $asset (précompilé, golem-binaries)"
fetch_verified "$GOLEM_PREBUILT_BASE/$asset.tar.gz" "$tmp/a.tar.gz" || { echo "  → précompilé indisponible : compilation depuis la source"; exit 1; }
mkdir -p "$tmp/x" "$dest"
tar -xzf "$tmp/a.tar.gz" -C "$tmp/x"
# -e, pas -d : un bundle VST3/LV2 est un dossier, un plugin CLAP un FICHIER (VM 2026-10-23 : les trois CLAP refusés)
[ -e "$tmp/x/$bundle" ] || { echo "  ✗ l'archive ne contient pas « $bundle » : compilation depuis la source"; exit 1; }
rm -rf "${dest:?}/$bundle"
mv "$tmp/x/$bundle" "$dest/$bundle"
echo "  ✓ $bundle posé dans $dest (précompilé)"
