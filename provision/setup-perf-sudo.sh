#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installe la règle sudoers qui autorise le bouton « performance » du dashboard GoleM.
# PORTABLE : génère la règle avec l'utilisateur et le chemin RÉELS de ce dépôt (marche sur le rack).
#   ./provision/setup-perf-sudo.sh   (demande ton mot de passe sudo une fois)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# S-P1-4 (audit sécu) : sudoers ne doit JAMAIS viser un script modifiable par l'utilisateur —
# copie ROOT-OWNED dans /usr/local/sbin (patron net.sh), c'est ELLE que sudoers autorise.
SBIN=/usr/local/sbin/golem-perf-mode
. "$ROOT/provision/lib-receipt.sh"
# reçu : le gouverneur CPU AVANT que golem le touche (le premier passage gagne). C'est ici, et pas dans
# perf-mode.sh, qu'on le note : la copie root-owned n'exécute JAMAIS un script modifiable par l'utilisateur.
gov="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true)"
[ -n "$gov" ] && receipt prior governor "$gov" --string
echo "→ copie root-owned $SBIN…"
sudo install -o root -g root -m 0755 "$ROOT/provision/perf-mode.sh" "$SBIN"
receipt_add "$SBIN" file system --owner root
USER_NAME="$(id -un)"
TMP="$(mktemp)"; trap 'rm -f "$TMP"' EXIT
cat > "$TMP" <<EOF
# GoleM — bouton performance du dashboard (gouverneur CPU sans mot de passe).
# Généré par provision/setup-perf-sudo.sh — copie root-owned, restreint aux verbes on/off.
$USER_NAME ALL=(root) NOPASSWD: $SBIN on, $SBIN off
EOF
echo "→ validation de la syntaxe…"
sudo visudo -cf "$TMP"
echo "→ installation dans /etc/sudoers.d/golem-perf…"
sudo install -m 0440 "$TMP" /etc/sudoers.d/golem-perf
receipt_add /etc/sudoers.d/golem-perf file system --owner root
echo "✓ OK — bouton ⚡ Enable performance actif (utilisateur $USER_NAME, script $SBIN)."
