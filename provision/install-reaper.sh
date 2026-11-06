#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installe Reaper (Linux x86_64) depuis le tarball officiel reaper.fm.
# Reaper est propriétaire (eval gratuit illimité, licence ~60$ à acheter).
# Version épinglée pour la reproductibilité ; bump volontaire.
set -euo pipefail

REAPER_VERSION="${REAPER_VERSION:-7.79}"   # ← vérifier https://www.reaper.fm/download.php et bumper
# SHA-256 du tarball épinglé (audit 2026-08-12, M-3) : un download se VÉRIFIE avant de
# s'installer. Bumper la version = re-calculer ce hash (sha256sum du .tar.xz officiel).
REAPER_SHA256="${REAPER_SHA256:-a420b47fc5a1bef2ba6ecbf4937bb67b094333f0daa318dfe702d5fcdaa38846}"
REAPER_MAJOR="${REAPER_VERSION%%.*}"
PKG="reaper${REAPER_VERSION/./}_linux_x86_64"
URL="https://www.reaper.fm/files/${REAPER_MAJOR}.x/${PKG}.tar.xz"
PREFIX="${HOME}/opt"
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"

# reçu (docs/uninstall.md §2) : un REAPER déjà là n'est pas le nôtre — la désinstallation ne l'offrira pas.
# On le note AVANT de toucher à quoi que ce soit ; le premier passage gagne (un 2e passage voit le nôtre).
prior_reaper() {   # $1 = chemin du binaire trouvé
  local dir ver=""
  dir="$(dirname "$(readlink -f "$1" 2>/dev/null || echo "$1")")"
  [ -f "$dir/whatsnew.txt" ] && ver="$(head -1 "$dir/whatsnew.txt" | grep -oE '[0-9]+\.[0-9]+' | head -1 || true)"
  receipt prior reaper.installed_by_golem false
  receipt prior reaper.path "$(receipt_tilde "$(dirname "$1")")" --string
  receipt prior reaper.version "${ver:-unknown}" --string
}

if command -v reaper >/dev/null 2>&1 && reaper --version 2>/dev/null | grep -q "$REAPER_VERSION"; then
  prior_reaper "$(command -v reaper)"
  echo "  Reaper $REAPER_VERSION déjà installé."; exit 0
fi
if [ -x "$PREFIX/REAPER/reaper" ]; then
  prior_reaper "$PREFIX/REAPER/reaper"           # celui d'avant golem (ou d'une install d'avant le reçu)
elif command -v reaper >/dev/null 2>&1; then
  prior_reaper "$(command -v reaper)"
fi

tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo "  Téléchargement $URL"
curl -fsSL "$URL" -o "$tmp/reaper.tar.xz"
if [ -n "$REAPER_SHA256" ]; then
  echo "$REAPER_SHA256  $tmp/reaper.tar.xz" | sha256sum -c --quiet - \
    || { echo "  ✗ SHA-256 inattendu — tarball refusé (MITM ou pin périmé ?)" >&2; exit 1; }
fi
tar -xf "$tmp/reaper.tar.xz" -C "$tmp"
mkdir -p "$PREFIX"
# L'installeur officiel : --install <dir> place dans <dir>/REAPER + intègre menu/desktop
"$tmp/reaper_linux_x86_64/install-reaper.sh" --install "$PREFIX" --integrate-user-desktop
echo "  Reaper installé dans $PREFIX/REAPER"
# vrai SEULEMENT si on vient de l'installer et qu'aucun REAPER n'était là avant (le premier gagne)
receipt prior reaper.installed_by_golem true
receipt prior reaper.path "$(receipt_tilde "$PREFIX/REAPER")" --string
receipt prior reaper.version "$REAPER_VERSION" --string
receipt_add "$PREFIX/REAPER" dir reaper
echo "  (binaire : $PREFIX/REAPER/reaper — ajoute ~/opt/REAPER au PATH si besoin)"
