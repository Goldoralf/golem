#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Capture une maquette HTML en PNG via google-chrome headless.
# Usage: tools/shoot.sh mockups/live.html scratch_qc/live.png [WIDTHxHEIGHT]
set -e
html="$(realpath "$1")"; out="$2"; size="${3:-1280,800}"
google-chrome --headless=new --disable-gpu --no-sandbox --hide-scrollbars \
  --force-device-scale-factor=2 --window-size="${size/x/,}" \
  --screenshot="$out" "file://$html" >/dev/null 2>&1
echo "$out"
