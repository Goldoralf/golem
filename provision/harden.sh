#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — durcissement rack (B5 du plan de consolidation) :
#   pare-feu minimal, MAJ auto figées, USB sans autosuspend, mDNS golem.local, gouverneur CPU « performance » au boot.
#
# 2026-10-16 (docs/installer.md §4) : un geste SÉPARÉ, plus jamais lié au démarrage avec la machine — System ▸ Dashboard
# ▸ « Lock down this machine » (bridge/machine.py, le mot de passe par askpass, jamais écrit) ou ce script à la main.
# Le gouverneur permanent (golem-perf.service) vient d'install-autostart.sh, qui ne durcit plus rien.
#
#   ./provision/harden.sh
#
# ⚠ Machines cibles uniquement (rack/VM) — même garde-fou que l'autostart.
# Idempotent : rejouable sans casser. Le reste du durcissement (licence Reaper,
# kernel lowlatency, BIOS auto-power-on) est manuel : provision/system-tuning.md.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
log() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
# reçu d'install (docs/uninstall.md §2) : chaque réglage partagé note son état d'AVANT, avant d'être touché
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"

if [ "${GOLEM_KIOSK_OK:-}" != "1" ]; then
  case "$(hostname)" in
    golem-vm|golem-rack|rack*) : ;;
    *) echo "✗ hostname « $(hostname) » ≠ rack/VM. Si voulu : GOLEM_KIOSK_OK=1 $0"; exit 1 ;;
  esac
fi

# --- 0. SSH durci (S-P1-5) : clés uniquement — SEULEMENT si une clé est déjà posée -----------
log "SSH (clés uniquement, root interdit)"
if [ -s "$HOME/.ssh/authorized_keys" ]; then
  receipt_add /etc/ssh/sshd_config.d/golem-harden.conf file dedicated --owner root
  sudo tee /etc/ssh/sshd_config.d/golem-harden.conf >/dev/null <<'SSHEOF'
# GoleM harden.sh — S-P1-5 : pas de mot de passe sur un rack de scène
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
SSHEOF
  sudo systemctl reload ssh 2>/dev/null || sudo systemctl reload sshd 2>/dev/null || true
else
  echo "⚠ pas de ~/.ssh/authorized_keys — durcissement SSH SAUTÉ (poser une clé d'abord, sinon lock-out)"
fi

# --- 1. Pare-feu : tout fermé sauf SSH + app + mDNS ---------------------------
log "Pare-feu (ufw : deny in, allow SSH/app/mDNS)"
# reçu : ufw AVANT (actif ? quelles règles ?) — la désinstallation retire nos règles et ne coupe ufw que s'il
# était inactif. ufw absent = inactif, sans règle. `ufw status` demande root.
if command -v ufw >/dev/null 2>&1; then
  sudo ufw status 2>/dev/null | python3 "$GOLEM_RECEIPT_PY" prior-ufw >/dev/null || true
else
  echo "Status: inactive" | python3 "$GOLEM_RECEIPT_PY" prior-ufw >/dev/null || true
fi
avahi="$(systemctl is-enabled avahi-daemon 2>/dev/null || true)"
receipt prior avahi_enabled "${avahi:-absent}" --string
receipt apt-snapshot before
APT_PKGS=(ufw avahi-daemon)
receipt apt-requested "${APT_PKGS[@]}"
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y "${APT_PKGS[@]}" >/dev/null
receipt apt-snapshot after
sudo ufw default deny incoming >/dev/null
sudo ufw default allow outgoing >/dev/null
sudo ufw allow OpenSSH >/dev/null                        # porte admin (Ethernet/LAN)
sudo ufw allow 8770/tcp comment 'GoleM app/API' >/dev/null
sudo ufw allow 80/tcp comment 'GoleM http://golem.local -> 8770' >/dev/null
sudo ufw allow 5353/udp comment 'mDNS golem.local' >/dev/null
sudo ufw --force enable
sudo ufw status | sed 's/^/  /'

# --- 2. mDNS : joindre le rack par nom, sans connaître l'IP -------------------
# Deux noms : `<machine>.local` (avahi, le nom du système) et `golem.local`, que le bridge annonce lui-même
# (bridge/reach.py, le même que sur un poste Windows/macOS). Le port 80 ouvert aux utilisateurs : le
# bridge y renvoie vers 8770, et `http://golem.local` suffit sur le téléphone (2026-10-03).
log "mDNS (avahi) : http://$(hostname).local:8770/app/ · http://golem.local"
sudo systemctl enable --now avahi-daemon >/dev/null 2>&1 || true
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/90-golem-port80.conf >/dev/null
receipt_add /etc/sysctl.d/90-golem-port80.conf file dedicated --owner root
sudo sysctl -q -p /etc/sysctl.d/90-golem-port80.conf || true

# --- 3. Figer les mises à jour automatiques -----------------------------------
# Un rack de scène ne se met PAS à jour tout seul (une MAJ ALSA/PipeWire la
# veille d'un concert = risque inacceptable). MAJ = geste volontaire par SSH.
log "MAJ automatiques figées (apt timers + unattended-upgrades)"
# reçu : l'état des minuteries apt d'avant ; le FICHIER 20auto-upgrades, plus bas (il était écrasé sans copie,
# docs/uninstall.md §8)
t1="$(systemctl is-enabled apt-daily.timer 2>/dev/null || true)"
t2="$(systemctl is-enabled apt-daily-upgrade.timer 2>/dev/null || true)"
receipt prior apt_timers "{\"apt-daily.timer\": \"${t1:-absent}\", \"apt-daily-upgrade.timer\": \"${t2:-absent}\"}"
sudo systemctl disable --now apt-daily.timer apt-daily-upgrade.timer >/dev/null 2>&1 || true
sudo systemctl mask apt-daily.service apt-daily-upgrade.service >/dev/null 2>&1 || true
if dpkg -l unattended-upgrades 2>/dev/null | grep -q '^ii'; then
  receipt prior auto_upgrades --file /etc/apt/apt.conf.d/20auto-upgrades   # avant de l'écraser (null = absent)
  sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<'EOF'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
EOF
fi
echo "  → MAJ manuelles : sudo apt update && sudo apt upgrade (jamais avant un gig)"

# --- 4. USB : pas d'autosuspend (Volt/AKAI/FCB doivent rester réveillés) ------
log "USB autosuspend désactivé (udev)"
receipt_add /etc/udev/rules.d/90-golem-usb-power.rules file dedicated --owner root
sudo tee /etc/udev/rules.d/90-golem-usb-power.rules >/dev/null <<'EOF'
# GoleM — l'audio/MIDI USB ne doit jamais être suspendu (xruns/déconnexions)
ACTION=="add", SUBSYSTEM=="usb", TEST=="power/control", ATTR{power/control}="on"
EOF
sudo udevadm control --reload-rules

# --- 5. Gouverneur CPU « performance » à chaque boot (golem-perf.service) -----
log "Gouverneur CPU performance au boot"
gov="$(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || true)"
[ -n "$gov" ] && receipt prior governor "$gov" --string      # avant que golem-perf le fige (le premier gagne)
receipt_add /etc/systemd/system/golem-perf.service file system --owner root
sudo install -m 644 "$HERE/autostart/system/golem-perf.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now golem-perf.service

cat <<EOF

✅ Durcissement appliqué.
   Manuel restant (system-tuning.md) : licence Reaper .rk · kernel lowlatency ·
   BIOS auto-power-on · Tailscale/VNC si accès distant hors LAN.
   Backups de contenu : app Settings ▸ Content (zips restaurables, backups/).
EOF
