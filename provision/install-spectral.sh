#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Les blocs SPECTRAUX (docs/spectral.md) : Spectral Compressor (nih-plug, Rust) et PaulXStretch (JUCE) —
# compilés DEPUIS LA SOURCE, commits épinglés, comme Prisma (install-prisma.sh). Ni l'un ni l'autre
# n'est packagé pour Linux ; PaulXStretch ne publie aucun binaire Linux du tout.
#
#   sudo ./provision/install-spectral.sh
#
# Ce script tourne en `sudo` : les en-têtes vont dans le système ; Rust (~/.cargo), la compilation et
# les plugins (~/.clap, ~/.vst3) chez l'APPELANT ($SUDO_USER), sinon Reaper ne les verrait jamais.
# Pas de JACK : la feature `standalone` de Spectral Compressor est retirée au build, `JUCE_JACK=0` pour
# PaulXStretch — un plugin n'ouvre jamais de device audio.
# Puis : REDÉMARRER Reaper (POST /api/system/reaper-restart) — il ne rescanne qu'au démarrage.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive   # aucun paquet ne pose de question : l'installateur n'a pas de terminal

NIH_REPO="https://github.com/robbert-vdh/nih-plug.git"
NIH_COMMIT="de421011f41a6d10fc8c7a6084e4f4dee0143683"      # master du 2026-09-03, construit sur le rack le 2026-09-25
PXS_REPO="https://github.com/essej/paulxstretch.git"
PXS_COMMIT="b6175e9"                                          # v1.6.0 (2022-10-02)
USER_NAME="${SUDO_USER:-$USER}"
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
USER_HOME="${USER_HOME:-$HOME}"
BUILD_ROOT="$USER_HOME/.cache/golem-build"
JOBS=$(nproc)
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"      # reçu d'install (sous sudo : celui de $SUDO_USER)
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-fetch.sh"        # fetch_verified : empreintes de downloads.sha256
RUSTUP_VERSION="1.28.2"
# un plugin posé : noté au reçu, avec « déjà là avant nous » si c'était le cas
place() {   # $1 = chemin final ; le reste = la commande (chez l'utilisateur) qui le pose
  local dst="$1" ex; shift
  ex=$(receipt_existed "$dst")
  run_as_user "$1"
  # shellcheck disable=SC2086
  receipt_add "$dst" dir plugins $ex
}

run_as_user() { sudo -u "$USER_NAME" -H bash -c "export PATH=\"$USER_HOME/.cargo/bin:\$PATH\"; $1"; }

# ── PRÉCOMPILÉS d'abord (Goldoralf/golem-binaries, mêmes commits) : sans eux, ni toolchain ni Rust à poser (~10 min)
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-prebuilt.sh"
# Freeze est NOTRE code : le binaire de la release n'est bon que pour la source qui l'a produit. Empreinte de cette
# source (Cargo.lock, Cargo.toml, golem_freeze/) au moment de linux-plugins-v1 (inchangée en v2) ; si plugins/ a bougé, on compile.
FREEZE_SRC_SHA="0873e47fcbb9af477d303e0d166b358503b15466832a32d8e69620ad66de10bc"
PLUGINS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/plugins"
freeze_src_sha() { (cd "$PLUGINS_DIR" && cat Cargo.lock Cargo.toml golem_freeze/Cargo.toml golem_freeze/src/*.rs | sha256sum | cut -c1-64); }
pre() {   # pre <asset> <dossier> <bundle> — posé et noté au reçu, ou 1
  local ex; ex=$(receipt_existed "$2/$3")
  prebuilt "$1" "$2" "$3" || return 1
  receipt_add "$2/$3" dir plugins $ex
}
NEED_SC=1; NEED_PXS=1; NEED_FREEZE=1
pre Spectral-Compressor.clap "$USER_HOME/.clap" "Spectral Compressor.clap" \
  && pre Spectral-Compressor.vst3 "$USER_HOME/.vst3" "Spectral Compressor.vst3" && NEED_SC=0
if pre PaulXStretch.vst3 "$USER_HOME/.vst3" PaulXStretch.vst3; then
  NEED_PXS=0
  pre PaulXStretch.clap "$USER_HOME/.clap" PaulXStretch.clap || true      # le CLAP est un bonus, comme à la compilation
fi
if [ "$(freeze_src_sha)" = "$FREEZE_SRC_SHA" ]; then
  pre GoleM-Freeze.clap "$USER_HOME/.clap" "GoleM Freeze.clap" \
    && pre GoleM-Freeze.vst3 "$USER_HOME/.vst3" "GoleM Freeze.vst3" && NEED_FREEZE=0
else
  echo "  → plugins/ a changé depuis linux-plugins-v1/v2 : GoleM Freeze sera compilé"
fi
# les bibliothèques que ces binaires chargent (readelf NEEDED) — sans les -dev de la compilation
runtime_libs libfftw3-single3 libasound2t64 libfreetype6 libgl1 libx11-6 libx11-xcb1 libxcb1 libxcb-icccm4
if [ "$NEED_SC$NEED_PXS$NEED_FREEZE" = 000 ]; then
  echo "✓ Spectral Compressor, PaulXStretch et GoleM Freeze posés (précompilés, GPL-3)"
  exit 0
fi

# toolchain + Rust 182 s, Spectral Compressor 85, PaulXStretch 140, Freeze 25 (mesurés en VM)
compiling $((182 + 85 * NEED_SC + 140 * NEED_PXS + 25 * NEED_FREEZE))
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

if [ "$NEED_SC$NEED_FREEZE" != 00 ]; then
echo "== 2. Rust (rustup, profil minimal, chez $USER_NAME, sans toucher au shell) =="
# reçu : Rust n'est « à nous » que si c'est nous qui l'installons (le premier passage gagne)
if ! run_as_user "command -v cargo >/dev/null"; then
  # audit 2026-11-04 (M8) : l'installateur rustup VERSIONNÉ, vérifié par son empreinte — plus de `curl | sh`
  RUSTUP_INIT=$(mktemp /tmp/golem-rustup-init.XXXXXX)
  fetch_verified "https://static.rust-lang.org/rustup/archive/$RUSTUP_VERSION/$(uname -m)-unknown-linux-gnu/rustup-init" "$RUSTUP_INIT"
  chmod 0755 "$RUSTUP_INIT"
  run_as_user "'$RUSTUP_INIT' -y --profile minimal --no-modify-path"
  rm -f "$RUSTUP_INIT"
  receipt prior toolchain.rust_installed_by_golem true
  receipt_add "$USER_HOME/.cargo" dir toolchain
  receipt_add "$USER_HOME/.rustup" dir toolchain
else
  receipt prior toolchain.rust_installed_by_golem false
fi
run_as_user "cargo --version"
fi

run_as_user "mkdir -p '$BUILD_ROOT'"          # avant les étapes : n'importe laquelle peut être la seule à compiler
receipt_add "$BUILD_ROOT" dir golem

if [ "$NEED_SC" = 1 ]; then
echo "== 3. Spectral Compressor (nih-plug, commit épinglé, sans 'standalone') =="
NIH_DIR="$BUILD_ROOT/nih-plug"
if [ ! -d "$NIH_DIR/.git" ]; then
  run_as_user "git clone --filter=blob:none '$NIH_REPO' '$NIH_DIR'"
fi
run_as_user "cd '$NIH_DIR' && git fetch -q origin && git checkout -q '$NIH_COMMIT'"
run_as_user "cd '$NIH_DIR' && sed -i 's/features = \[\"assert_process_allocs\", \"standalone\"\]/features = [\"assert_process_allocs\"]/' plugins/spectral_compressor/Cargo.toml"
run_as_user "cd '$NIH_DIR' && cargo xtask bundle spectral_compressor --release"
run_as_user "mkdir -p '$USER_HOME/.clap' '$USER_HOME/.vst3'"
place "$USER_HOME/.clap/Spectral Compressor.clap" \
  "rm -rf '$USER_HOME/.clap/Spectral Compressor.clap' && cp -r '$NIH_DIR/target/bundled/Spectral Compressor.clap' '$USER_HOME/.clap/'"
place "$USER_HOME/.vst3/Spectral Compressor.vst3" \
  "rm -rf '$USER_HOME/.vst3/Spectral Compressor.vst3' && cp -r '$NIH_DIR/target/bundled/Spectral Compressor.vst3' '$USER_HOME/.vst3/'"
echo "✓ Spectral Compressor posé (.clap + .vst3, GPL-3.0-or-later)"
fi

if [ "$NEED_PXS" = 1 ]; then
echo "== 4. PaulXStretch (JUCE + FFTW, commit épinglé, VST3 + CLAP, sans JACK ni standalone) =="
PXS_DIR="$BUILD_ROOT/paulxstretch"
if [ ! -d "$PXS_DIR/.git" ]; then
  run_as_user "git clone --recurse-submodules --shallow-submodules '$PXS_REPO' '$PXS_DIR'"
fi
run_as_user "cd '$PXS_DIR' && git fetch -q origin && git checkout -q '$PXS_COMMIT' && git submodule update --init --recursive"
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

if [ "$NEED_FREEZE" = 1 ]; then
echo "== 5. GoleM Freeze (notre bloc, plugins/golem_freeze — nih-plug, même toolchain) =="
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
run_as_user "cd '$HERE/plugins' && cargo xtask bundle golem_freeze --release"
place "$USER_HOME/.clap/GoleM Freeze.clap" \
  "rm -rf '$USER_HOME/.clap/GoleM Freeze.clap' && cp -r '$HERE/plugins/target/bundled/GoleM Freeze.clap' '$USER_HOME/.clap/'"
place "$USER_HOME/.vst3/GoleM Freeze.vst3" \
  "rm -rf '$USER_HOME/.vst3/GoleM Freeze.vst3' && cp -r '$HERE/plugins/target/bundled/GoleM Freeze.vst3' '$USER_HOME/.vst3/'"
echo "✓ GoleM Freeze posé (.clap + .vst3, GPL-3)"
fi
echo "  Puis : redémarrer Reaper (Settings ▸ System ▸ Reaper restart, ou POST /api/system/reaper-restart),"
echo "  et valider : check-block-stall.py, fxparams, deux reconstructions — AVANT de l'offrir à l'IA."
