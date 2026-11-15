#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# golem-fx (les effets de golem, GPL-3) sous Linux : la release précompilée golem-fx-0.4 de Goldoralf/golem-binaries,
# épinglée dans provision/downloads.sha256 (fetch_verified la refuse si son empreinte change), posée dans ~/.vst3 —
# le dossier que REAPER parcourt et que bridge/rig.py lit (_golem_fx_installed). Au reçu d'install : le désinstalleur
# retire chaque bundle. Un build de dev de tools/golem-fx-install.py (son journal) est GARDÉ, et la ligne le dit.
# Rend 1 si rien n'est posé : install.sh le dit (soft_fail) et continue — les blocs gardent leurs plugins d'origine.
# Les .so demandent une glibc ≥ 2.34 (Ubuntu 22.04+, Debian 12+) : en dessous, REAPER ne les charge pas et les blocs
# gardent aussi leur plugin d'origine (golem_rig ne bascule que vers un plugin que REAPER a scanné).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/lib-fetch.sh"
GFX_VERSION="0.4"
GFX_ASSET="golem-fx-linux-x86_64.tar.gz"
GFX_URL="https://github.com/Goldoralf/golem-binaries/releases/download/golem-fx-${GFX_VERSION}/${GFX_ASSET}"
case "$(uname -m)" in
  x86_64) ;;
  *) echo "  ⚠ golem-fx : pas de build pour $(uname -m) — les blocs gardent leurs plugins d'origine"; exit 1 ;;
esac
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo "  ↓ golem-fx $GFX_VERSION (précompilé, golem-binaries)"
fetch_verified "$GFX_URL" "$tmp/$GFX_ASSET" || exit 1
# la pose et le reçu (provision/receipt.py, chaque bundle) : provision/golem_fx.py, le même code que sous Windows et
# macOS — python3 du système
python3 "$HERE/golem_fx.py" --place "$tmp/$GFX_ASSET" --dest "$HOME/.vst3"
