#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installe sfizz (sampler SFZ, LV2) — bloc `piano` de la lane Keys (docs/archive/keys-rig-plan.md).
# Pas de paquet dans Ubuntu 24.04 : les .deb de sfztools (OBS), épinglés, pris à la première source qui répond.
#   sudo ./provision/install-sfizz.sh
#
# ⚠ VÉCU LE 2026-09-09, validation VM « OS nu » (docs/installer.md §7) : la clé du dépôt OBS a
# EXPIRÉ en amont (EXPKEYSIG 1DCC29D5F18761E8) — `apt-get update` rend 100, et l'installation
# ENTIÈRE mourait là, avant le bridge et avant les sons, pour UN bloc. Deux leçons, appliquées ici :
#   1. une source tierce cassée se CONTOURNE (les .deb s'installent sans signature de dépôt ;
#      on vérifie qu'un .deb est bien un .deb, comme fetch-assets vérifie ses assets) ;
#   2. on ne laisse JAMAIS un sources.list.d cassé derrière soi : il casserait TOUS les apt
#      suivants de la machine, longtemps après notre passage, et pour une raison illisible.
#
# ⚠ 2026-10-23, VM « OS nu » : le dépôt OBS de sfztools est RETIRÉ (dossier vide, Release.key en 404) — plus
# seulement sa clé expirée. Le piano de la lane Keys et les kits SFZ restaient muets sur tout golem Linux neuf,
# et l'installation finissait « ok ». Plus de dépôt apt : les deux .deb ÉPINGLÉS (provision/downloads.sha256),
# pris à la première SOURCE qui répond. La même empreinte vaut pour chaque source : un miroir ne peut rien
# glisser d'autre. La release de golem passe d'abord — elle ne disparaîtra pas sous nos pieds.
set -euo pipefail

VER="1.2.3-0"
# les sources, dans l'ordre : chacune a ses lignes dans provision/downloads.sha256 (mêmes empreintes)
SOURCES=(
  "https://github.com/Goldoralf/golem-binaries/releases/download/sfizz-1.2.3-golem"
  "https://download.opensuse.org/repositories/home:/sfztools:/sfizz/xUbuntu_24.04/amd64"
  "https://ftp.gwdg.de/pub/opensuse/repositories/home:/sfztools:/sfizz/xUbuntu_24.04/amd64"
)
APT=(env DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold)
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"      # reçu d'install (sous sudo : celui de $SUDO_USER)
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-fetch.sh"

# ⚠ PAS de `ls A B | grep` ici : avec `pipefail`, un `ls` sur un dossier ABSENT rend 2, le pipeline
# rend 2, et la vérification dit « introuvable » alors que grep a trouvé. Vécu en VM le 2026-09-09 :
# sfizz était installé, le script l'a nié et a rendu 1. Un test de présence se fait sur le chemin.
have() { [ -d /usr/lib/lv2/sfizz.lv2 ] || [ -d /usr/lib/x86_64-linux-gnu/lv2/sfizz.lv2 ]; }
if have; then echo "✓ sfizz déjà installé"; exit 0; fi

# l'ancien dépôt apt, s'il traîne d'une install d'avant : il casserait tous les apt suivants
rm -f /etc/apt/sources.list.d/sfizz.list /etc/apt/trusted.gpg.d/sfizz.gpg

tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
LIB="libsfizz1_${VER}_amd64.deb"; APP="sfizz_${VER}_amd64.deb"
for p in "$LIB" "$APP"; do
  ok=0
  for src in "${SOURCES[@]}"; do
    host="${src#https://}"; echo "  ↓ $p ← ${host%%/*}"
    if fetch_verified "$src/$p" "$tmp/$p"; then ok=1; break; fi
  done
  [ "$ok" = 1 ] || { echo "✗ $p introuvable sur toutes les sources — sfizz non installé"; exit 1; }
done
# reçu : les noms sont lus dans les .deb ; à nous seulement s'ils n'étaient pas installés
newdebs=()
for p in "$LIB" "$APP"; do
  pkg="$(dpkg-deb -f "$tmp/$p" Package 2>/dev/null || true)"
  if [ -n "$pkg" ] && [ "$(dpkg-query -W -f='${db:Status-Status}' "$pkg" 2>/dev/null || true)" != installed ]; then
    newdebs+=("$pkg")
  fi
done
receipt apt-snapshot before
for p in "$LIB" "$APP"; do receipt apt-requested "$(dpkg-deb -f "$tmp/$p" Package 2>/dev/null || true)"; done
"${APT[@]}" install -y "$tmp/$LIB" "$tmp/$APP"
for pkg in "${newdebs[@]}"; do receipt deb "$pkg"; done
receipt apt-snapshot after

echo "→ vérification LV2"
have && echo "✓ sfizz.lv2 installé" || { echo "✗ bundle LV2 introuvable"; exit 1; }
