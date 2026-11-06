#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Plugins distribués en .deb (releases GitHub). Installés système → sudo dpkg.
# Outils neuraux ("IA") knob-controllables + pédalier modulaire.
# Versions épinglées (reproductibilité) ; bump volontaire.
set -euo pipefail
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-fetch.sh"      # fetch_verified : empreintes épinglées
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"    # reçu d'install : apt.debs + dépendances

declare -A DEBS=(
  # GuitarML Proteus — ampli/pédale neural, charge les modèles .json GuitarML (TS9, 5150, Klon...)
  [Proteus]="https://github.com/GuitarML/Proteus/releases/download/v1.2/Proteus-Linux-x64-1.2.deb"
  # ChowDSP BYOD — "Build Your Own Distortion" : pédalier modulaire, blocs RTNeural + FX analog-modélisés
  [BYOD]="https://github.com/Chowdhury-DSP/BYOD/releases/download/v1.3.0/BYOD-Linux-x64-1.3.0.deb"
  # GuitarML Chameleon — ampli neural (optionnel, décommente si voulu)
  # [Chameleon]="https://github.com/GuitarML/Chameleon/releases/download/v1.2.0/Chameleon-Linux-x64-1.2.0.deb"
)

for name in "${!DEBS[@]}"; do
  echo "  ↓ $name"
  if ! fetch_verified "${DEBS[$name]}" "$tmp/$name.deb"; then continue; fi
  # reçu : le NOM du paquet est lu dans le .deb (proteus, byod…), jamais deviné ; il n'est à nous que s'il
  # n'était pas déjà installé. Ses dépendances vont dans apt.added (photo avant / après).
  pkg="$(dpkg-deb -f "$tmp/$name.deb" Package 2>/dev/null || true)"
  was="$(dpkg-query -W -f='${db:Status-Status}' "$pkg" 2>/dev/null || true)"
  receipt apt-snapshot before
  if [ -n "$pkg" ]; then receipt apt-requested "$pkg"; fi
  sudo DEBIAN_FRONTEND=noninteractive dpkg -i "$tmp/$name.deb" 2>/dev/null || sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -f -y
  if [ -n "$pkg" ] && [ "$was" != installed ]; then receipt deb "$pkg"; fi
  receipt apt-snapshot after
  echo "    ✓ $name installé"
done

echo "  → Plugins .deb installés (VST3/LV2 système). Dans Reaper : re-scan VST3 + LV2."
