#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Le bloc STRETCH (docs/spectral.md) : PaulXStretch (JUCE) — précompilé (golem-binaries), sinon compilé DEPUIS LA
# SOURCE, commit épinglé. Il n'est pas packagé pour Linux et ne publie aucun binaire Linux.
# Spectral Compressor (nih-plug, Rust) : RETIRÉ (2026-11-27) — gfx-spectralcomp joue le bloc Spectral Comp
# (docs/golem-fx-migration.md). Plus de Rust à poser. Le désinstallateur garde ses entrées : une install plus ancienne
# a posé le plugin et peut-être Rust.
#
#   sudo ./provision/install-spectral.sh
#
# Ce script tourne en `sudo` : les en-têtes vont dans le système ; la compilation et les plugins (~/.clap,
# ~/.vst3) chez l'APPELANT ($SUDO_USER), sinon Reaper ne les verrait jamais.
# Pas de JACK : `JUCE_JACK=0` — un plugin n'ouvre jamais de device audio.
# Puis : REDÉMARRER Reaper (POST /api/system/reaper-restart) — il ne rescanne qu'au démarrage.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive   # aucun paquet ne pose de question : l'installateur n'a pas de terminal

PXS_REPO="https://github.com/essej/paulxstretch.git"
PXS_COMMIT="b6175e9"                                          # v1.6.0 (2022-10-02)
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
USER_HOME="${USER_HOME:-$HOME}"
BUILD_ROOT="$USER_HOME/.cache/golem-build"
JOBS=$(nproc)
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"      # reçu d'install (sous sudo : celui de $SUDO_USER)
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-fetch.sh"        # fetch_verified : empreintes de downloads.sha256
# un plugin posé : noté au reçu, avec « déjà là avant nous » si c'était le cas
place() {   # $1 = chemin final ; le reste = la commande (chez l'utilisateur) qui le pose
  local dst="$1" ex; shift
  ex=$(receipt_existed "$dst")
  run_as_user "$1"
  # shellcheck disable=SC2086
  receipt_add "$dst" dir plugins $ex
}

run_as_user() { sudo -u "$USER_NAME" -H bash -c "$1"; }

# ── PRÉCOMPILÉ d'abord (Goldoralf/golem-binaries, même commit) : sans lui, toute une toolchain à poser
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-prebuilt.sh"
# GoleM Freeze (plugins/golem_freeze) : RETIRÉ de l'install (2026-11-15) — le bloc freeze est retiré (devenu granular,
# catalogue v48). Le désinstallateur garde son entrée : une install plus ancienne l'a posé.
pre() {   # pre <asset> <dossier> <bundle> — posé et noté au reçu, ou 1
  local ex; ex=$(receipt_existed "$2/$3")
  prebuilt "$1" "$2" "$3" || return 1
  receipt_add "$2/$3" dir plugins $ex
}
NEED_PXS=1
if pre PaulXStretch.vst3 "$USER_HOME/.vst3" PaulXStretch.vst3; then
  NEED_PXS=0
  pre PaulXStretch.clap "$USER_HOME/.clap" PaulXStretch.clap || true      # le CLAP est un bonus, comme à la compilation
fi
# les bibliothèques que ces binaires chargent (readelf NEEDED) — sans les -dev de la compilation
runtime_libs libfftw3-single3 libasound2t64 libfreetype6 libgl1 libx11-6 libx11-xcb1 libxcb1 libxcb-icccm4
if [ "$NEED_PXS" = 0 ]; then
  echo "✓ PaulXStretch posé (précompilé, GPL-3)"
  exit 0
fi

# PaulXStretch 140 s mesuré en VM ; la toolchain apt, mesurée avec Rust (182 s), compte ici pour 60 s — une estimation
compiling $((60 + 140))
echo "== 1. Toolchain + en-têtes (apt) =="
# une seule liste : celle qu'on demande à apt est celle que le reçu note comme explicite (apt.requested)
APT_PKGS=(cmake build-essential git pkg-config curl
          libasound2-dev libx11-dev libxrandr-dev libxinerama-dev libxcursor-dev libxext-dev
          libfreetype-dev libfontconfig1-dev libgl1-mesa-dev libcurl4-openssl-dev
          libfftw3-dev
          libx11-xcb-dev libxcb-icccm4-dev libxkbcommon-dev libxcb-shape0-dev libxcb-xfixes0-dev
          libxcb-dri2-0-dev libxcb-dri3-dev)
receipt apt-snapshot before
receipt apt-requested "${APT_PKGS[@]}"
apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -y "${APT_PKGS[@]}"
receipt apt-snapshot after

run_as_user "mkdir -p '$BUILD_ROOT'"          # avant les étapes : n'importe laquelle peut être la seule à compiler
receipt_add "$BUILD_ROOT" dir golem

if [ "$NEED_PXS" = 1 ]; then
echo "== 2. PaulXStretch (JUCE + FFTW, commit épinglé, VST3 + CLAP, sans JACK ni standalone) =="
PXS_DIR="$BUILD_ROOT/paulxstretch"
if [ ! -d "$PXS_DIR/.git" ]; then
  run_as_user "git clone --recurse-submodules --shallow-submodules '$PXS_REPO' '$PXS_DIR'"
fi
run_as_user "cd '$PXS_DIR' && git fetch -q origin && git checkout -q '$PXS_COMMIT' && git submodule update --init --recursive"
run_as_user "mkdir -p '$USER_HOME/.clap' '$USER_HOME/.vst3'"
run_as_user "cd '$PXS_DIR' && sed -i 's/JUCE_JACK=1/JUCE_JACK=0/; s/set (FormatsToBuild VST3 CLAP Standalone)/set (FormatsToBuild VST3 CLAP)/' CMakeLists.txt"
run_as_user "cd '$PXS_DIR' && cmake -DCMAKE_BUILD_TYPE=Release -DJUCE_COPY_PLUGIN_AFTER_BUILD=OFF -B build"
run_as_user "cd '$PXS_DIR' && cmake --build build --config Release -j '$JOBS'"
ART="$PXS_DIR/build/PaulXStretch_artefacts/Release"
[ -d "$ART/VST3/PaulXStretch.vst3" ] || { echo "✗ PaulXStretch.vst3 introuvable après compilation"; exit 1; }
place "$USER_HOME/.vst3/PaulXStretch.vst3" \
  "rm -rf '$USER_HOME/.vst3/PaulXStretch.vst3' && cp -r '$ART/VST3/PaulXStretch.vst3' '$USER_HOME/.vst3/'"
if [ -e "$ART/CLAP/PaulXStretch.clap" ]; then
  place "$USER_HOME/.clap/PaulXStretch.clap" \
    "rm -rf '$USER_HOME/.clap/PaulXStretch.clap' && cp -r '$ART/CLAP/PaulXStretch.clap' '$USER_HOME/.clap/'"
else
  run_as_user "rm -rf '$USER_HOME/.clap/PaulXStretch.clap'"
fi
echo "✓ PaulXStretch posé (.vst3 + .clap, GPL-3)"
fi

echo "  Puis : redémarrer Reaper (Settings ▸ System ▸ Reaper restart, ou POST /api/system/reaper-restart),"
echo "  et valider : check-block-stall.py, fxparams, deux reconstructions — AVANT de l'offrir à l'IA."
