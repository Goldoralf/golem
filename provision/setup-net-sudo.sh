#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — installe la couche réseau système (docs/network.md) :
#  1. copie ROOT-OWNED de net.sh → /usr/local/sbin/golem-net (chemin repo baked)
#  2. sudoers NOPASSWD sur les verbes MUTANTS uniquement, via cette copie
#  3. seed config/network.json (SSID/pass AP) s'il n'existe pas
#  4. golem-net.service (fallback AP au boot)
# Rejouable (mise à jour de net.sh = relancer ce script).
#   ./provision/setup-net-sudo.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(id -un)"
BIN=/usr/local/sbin/golem-net
. "$ROOT/provision/lib-receipt.sh"

echo "→ 0/4 NetworkManager (absent d'un Ubuntu server vierge — networkd par défaut)"
if ! command -v nmcli >/dev/null 2>&1; then
  receipt apt-snapshot before
  receipt apt-requested network-manager
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y network-manager
  receipt apt-snapshot after
  echo "  ⚠ NM installé mais les interfaces restent gérées par netplan/networkd."
  echo "    Sur le RACK (écran branché !) : passer le renderer netplan à NetworkManager"
  echo "    puis netplan apply — cf. docs/network.md §Séquencement, étape 7."
fi

echo "→ 1/4 copie root-owned $BIN (repo : $ROOT)"
TMPBIN="$(mktemp)"; trap 'rm -f "$TMPBIN"' EXIT
sed "s|@ROOT@|$ROOT|" "$ROOT/provision/net.sh" > "$TMPBIN"
bash -n "$TMPBIN"
sudo install -o root -g root -m 0755 "$TMPBIN" "$BIN"
receipt_add "$BIN" file system --owner root

echo "→ 2/4 sudoers (verbes mutants uniquement)"
TMPSUDO="$(mktemp)"
cat > "$TMPSUDO" <<EOF
# GoleM — réseau (onglet Network + fallback AP). Généré par setup-net-sudo.sh.
# Seule la copie root-owned est autorisée — jamais le script du repo.
$USER_NAME ALL=(root) NOPASSWD: $BIN join *, $BIN up *, $BIN down *, $BIN forget *, $BIN ap-up, $BIN ap-down, $BIN boot-fallback
EOF
sudo visudo -cf "$TMPSUDO"
sudo install -m 0440 "$TMPSUDO" /etc/sudoers.d/golem-net
receipt_add /etc/sudoers.d/golem-net file system --owner root
rm -f "$TMPSUDO"

echo "→ 3/4 config/network.json"
if [ ! -f "$ROOT/config/network.json" ]; then
  # mot de passe AP par défaut aléatoire (à personnaliser dans l'onglet Network)
  # S-P2-4 : 16 chars aléatoires (~82 bits) — un PSK court se brute-force offline (handshake WPA2)
  # ⚠ PAS de « … | head -c 16 » : head ferme le tuyau, tr reçoit SIGPIPE, et sous
  # `set -o pipefail` toute l'install meurt en 141. Le bug dormait parce que ce script
  # n'était jamais appelé depuis install.sh — l'y brancher l'a réveillé (2026-08-02).
  # Ici le producteur se termine NORMALEMENT et c'est cut qui tronque.
  PSK="golem-$(LC_ALL=C tr -dc 'a-z0-9' < <(head -c 1024 /dev/urandom) | cut -c1-16)"
  cat > "$ROOT/config/network.json" <<EOF
{
  "_comment": "Réseau rack (docs/network.md). GITIGNORÉ (psk = secret).",
  "ap": { "ssid": "golem", "psk": "$PSK", "band": "bg" },
  "fallback_timeout_s": 30
}
EOF
  echo "  → créé (mot de passe AP généré : $PSK)"
else
  echo "  → déjà présent, inchangé."
fi

echo "→ 4/4 golem-net.service (fallback AP au boot)"
sudo tee /etc/systemd/system/golem-net.service >/dev/null <<EOF
# GoleM — fallback réseau au boot : station connue sinon AP (docs/network.md)
[Unit]
Description=GoleM network fallback (station sinon AP)
After=NetworkManager.service
Wants=NetworkManager.service

[Service]
Type=oneshot
ExecStart=$BIN boot-fallback
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF
receipt_add /etc/systemd/system/golem-net.service file system --owner root
# (le profil NetworkManager golem-ap et /etc/NetworkManager/dnsmasq-shared.d/golem-name.conf naissent plus
# tard, de net.sh en root : il n'appelle JAMAIS un script du dépôt — la désinstallation les retrouve par leur nom)
sudo systemctl daemon-reload
sudo systemctl enable golem-net.service

echo "✓ réseau installé — test manuel : sudo $BIN boot-fallback (écran branché la 1re fois !)"
