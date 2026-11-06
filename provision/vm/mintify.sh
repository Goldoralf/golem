#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# golem — rend une VM Ubuntu 24.04 « Linux Mint 22 » LÀ OÙ GOLEM LE VOIT (2026-11-03). Lancé en root par
# `GOLEM_VM_DISTRO=mint22 vm.sh create` (vm.sh l'envoie par ssh). Linux Mint ne publie pas d'image cloud, et son
# installateur n'a pas d'install sans clic : on part de l'Ubuntu dont Mint 22 est faite, et on lui donne ce qui change
# pour golem :
#   · snapd RETIRÉ et BLOQUÉ (nosnap.pref, comme Mint) : pas de Chromium snap ;
#   · le dépôt Mint, prioritaire (700, comme Mint) : son paquet `chromium` (un vrai .deb) et ses versions ;
#   · /etc/os-release et /etc/lsb-release de Mint : ID=linuxmint, VERSION_CODENAME=wilma, UBUNTU_CODENAME=noble —
#     un script qui construit une URL de dépôt avec VERSION_CODENAME se trompe ici comme chez un vrai utilisateur.
# Ce n'est PAS une Mint complète (ni Cinnamon, ni mintupdate) : une VM de test d'install, sans bureau.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# 1. snapd : retiré, puis bloqué comme sur Mint
apt-get purge -y snapd >/dev/null 2>&1 || true
rm -rf /snap /var/snap /var/lib/snapd
cat > /etc/apt/preferences.d/nosnap.pref <<'EOF'
# golem test VM — as on Linux Mint: snapd is blocked
Package: snapd
Pin: release a=*
Pin-Priority: -10
EOF

# 2. le dépôt Mint. Sa clé vient du paquet linuxmint-keyring de ce même dépôt, téléchargé en HTTP : acceptable pour une
# VM jetable, pas pour une machine réelle. Le paquet le plus récent du dossier (tri par version).
POOL=http://packages.linuxmint.com/pool/main/l/linuxmint-keyring
deb=$(curl -fsSL "$POOL/" | grep -o 'linuxmint-keyring_[^"<>]*_all\.deb' | sort -uV | tail -n1)
[ -n "$deb" ] || { echo "✗ linuxmint-keyring introuvable dans $POOL" >&2; exit 1; }
curl -fsSL -o /tmp/linuxmint-keyring.deb "$POOL/$deb"
dpkg -i /tmp/linuxmint-keyring.deb >/dev/null
rm -f /tmp/linuxmint-keyring.deb
echo "deb http://packages.linuxmint.com wilma main upstream import backport" \
  > /etc/apt/sources.list.d/official-package-repositories.list
cat > /etc/apt/preferences.d/official-package-repositories.pref <<'EOF'
# golem test VM — as on Linux Mint: its own repository wins
Package: *
Pin: origin packages.linuxmint.com
Pin-Priority: 700
EOF

# 3. l'identité Mint (le fichier réel est /usr/lib/os-release ; /etc/os-release en est le lien)
cat > /usr/lib/os-release <<'EOF'
NAME="Linux Mint"
VERSION="22 (Wilma)"
ID=linuxmint
ID_LIKE="ubuntu debian"
PRETTY_NAME="Linux Mint 22"
VERSION_ID="22"
VERSION_CODENAME=wilma
UBUNTU_CODENAME=noble
EOF
cat > /etc/lsb-release <<'EOF'
DISTRIB_ID=LinuxMint
DISTRIB_RELEASE=22
DISTRIB_CODENAME=wilma
DISTRIB_DESCRIPTION="Linux Mint 22 Wilma"
EOF

apt-get update -qq
echo "✓ Mint 22 (simulée) : snapd bloqué, dépôt Mint actif — chromium candidat : $(LC_ALL=C apt-cache policy chromium | awk '$1 == "Candidate:" { print $2 }')"
