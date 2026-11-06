#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Prisma (UnplugRed) — distorsion multibande modulaire, bloc « Grit » (docs/blocks-doctrine.md,
# addendum 2026-09-14 quinquies). Aucun binaire Linux n'est distribué hors Patreon : on COMPILE
# depuis la source (AGPLv3-or-later, github.com/unplugred/vsts), commit épinglé, variante FREE
# (bannière dans l'interface — que le rack n'affiche jamais ; l'auteur vit de la version payante,
# on ne fabrique pas la « paid » depuis sa source).
#
#   sudo ./provision/install-prisma.sh
#
# Ce script tourne en `sudo` : les dépendances vont dans le système, la compilation et le VST3
# chez l'APPELANT ($SUDO_USER : ~/.vst3/Prisma.vst3), sinon Reaper ne le verrait pas.
# Puis : REDÉMARRER Reaper (POST /api/system/reaper-restart) — il ne rescanne qu'au démarrage.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive   # aucun paquet ne pose de question : l'installateur n'a pas de terminal

VSTS_REPO="https://github.com/unplugred/vsts.git"
VSTS_COMMIT="5062b597b01d11507ed60ac9a7e0e7ad6dcfd63f"     # main du 2026-09-14, relu : processor.cpp = 25 params/bande
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
USER_HOME="${USER_HOME:-$HOME}"
BUILD_DIR="$USER_HOME/.cache/golem-build/unplugred-vsts"
JOBS=$(nproc)
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"      # reçu d'install (sous sudo : celui de $SUDO_USER)

. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-prebuilt.sh"
# PRÉCOMPILÉ d'abord (Goldoralf/golem-binaries, même commit)
ex=$(receipt_existed "$USER_HOME/.vst3/Prisma.vst3")
if prebuilt Prisma.vst3 "$USER_HOME/.vst3" Prisma.vst3; then
  runtime_libs libfreetype6 libgl1
  receipt_add "$USER_HOME/.vst3/Prisma.vst3" dir plugins $ex
  echo "✓ $USER_HOME/.vst3/Prisma.vst3 posé (commit ${VSTS_COMMIT:0:7}, AGPLv3, variante free, précompilé)"
  exit 0
fi

compiling 168
echo "== 1. Toolchain + en-têtes JUCE (apt) =="
# une seule liste : celle qu'on demande à apt est celle que le reçu note comme explicite (apt.requested)
APT_PKGS=(cmake build-essential git pkg-config
          libasound2-dev libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxext-dev
          libfreetype-dev libfontconfig1-dev libgl1-mesa-dev libcurl4-openssl-dev)
receipt apt-snapshot before
receipt apt-requested "${APT_PKGS[@]}"
apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -y "${APT_PKGS[@]}"
receipt apt-snapshot after

echo "== 2. Source (commit épinglé) =="
run_as_user() { sudo -u "$USER_NAME" -H bash -c "$1"; }
run_as_user "mkdir -p '$(dirname "$BUILD_DIR")'"
receipt_add "$(dirname "$BUILD_DIR")" dir golem
if [ ! -d "$BUILD_DIR/.git" ]; then
  run_as_user "git clone --filter=blob:none '$VSTS_REPO' '$BUILD_DIR'"
fi
run_as_user "cd '$BUILD_DIR' && git fetch -q origin && git checkout -q '$VSTS_COMMIT'"

echo "== 3. Compilation Prisma_VST3 (Release, variante free, ~5 min à $JOBS cœurs) =="
# JUCE est tiré par FetchContent (7.0.12) au premier configure : réseau requis.
run_as_user "cd '$BUILD_DIR' && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DBANNERTYPE=0 -DJUCE_COPY_PLUGIN_AFTER_BUILD=OFF"
run_as_user "cd '$BUILD_DIR' && cmake --build build --config Release --target Prisma_VST3 -j '$JOBS'"

echo "== 4. Pose dans ~/.vst3 de $USER_NAME =="
VST3=$(find "$BUILD_DIR/build" -type d -name "Prisma.vst3" | head -1)
[ -n "$VST3" ] || { echo "✗ Prisma.vst3 introuvable après compilation"; exit 1; }
ex=$(receipt_existed "$USER_HOME/.vst3/Prisma.vst3")
run_as_user "mkdir -p '$USER_HOME/.vst3' && rm -rf '$USER_HOME/.vst3/Prisma.vst3' && cp -r '$VST3' '$USER_HOME/.vst3/'"
# shellcheck disable=SC2086
receipt_add "$USER_HOME/.vst3/Prisma.vst3" dir plugins $ex
echo "✓ $USER_HOME/.vst3/Prisma.vst3 posé (commit ${VSTS_COMMIT:0:7}, AGPLv3, variante free)"
echo "  Puis : redémarrer Reaper (Settings ▸ System ▸ Reaper restart, ou POST /api/system/reaper-restart),"
echo "  et valider : bloc Grit seul dans une lane vide, deux reconstructions, fxparams — AVANT de l'offrir à l'IA."
