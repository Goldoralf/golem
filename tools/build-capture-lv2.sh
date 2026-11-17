#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Compile et installe « golem Capture » en LV2 (native/capture-lv2) : le lecteur des captures pilotables pour le Golem
# Engine, qui n'héberge pas le CLAP de native/capture. Installe dans ~/.lv2/golem-capture.lv2 (ou $1).
# Besoins : cmake, un compilateur C++20, les en-têtes LV2 (lv2-dev), et le réseau à la première compilation (le cœur
# NAM paramétrique épinglé est cloné). Le moteur doit être relancé pour voir le plugin.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$HOME/.lv2/golem-capture.lv2}"
BUILD="${GOLEM_CAPTURE_LV2_BUILD:-${XDG_CACHE_HOME:-$HOME/.cache}/golem/capture-lv2}"
cmake -S "$ROOT/native/capture-lv2" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release >/dev/null
cmake --build "$BUILD" --parallel "$(nproc)" | tail -1
mkdir -p "$DEST"
install -m 0644 "$BUILD/golem-capture.lv2/manifest.ttl" "$BUILD/golem-capture.lv2/golem-capture.ttl" "$DEST/"
install -m 0755 "$BUILD/golem-capture.lv2/golem-capture.so" "$DEST/"
echo "golem Capture (LV2) -> $DEST"
