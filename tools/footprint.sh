#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Empreinte d'une machine, pour juger une désinstallation (docs/uninstall.md §7) : tout ce qu'une installation du
# golem peut toucher, une ligne par fait, triée — deux relevés se comparent avec `diff`. Lecture seule.
# Lancé DANS la VM de test (sudo sans mot de passe y est réglé par cloud-init) ; jamais utile sur un rack.
set -u
S="sudo -n"; $S true 2>/dev/null || S=""   # sans sudo : ce qui est lisible sans root
sec() { printf '\n## %s\n' "$1"; }

sec "packages"
# les NOMS seuls : une montée de version d'un paquet de base n'est pas une trace (elle va dans « versions »). Un
# paquet retiré sans purge reste visible avec son état (« nom (config-files) ») ; « not-installed » ne compte pas.
dpkg-query -W -f='${Package} ${db:Status-Status}\n' 2>/dev/null \
  | awk '$2 == "installed" {print $1; next} $2 != "not-installed" {print $1 " (" $2 ")"}' | sort

sec "versions"
dpkg-query -W -f='${Package} ${db:Status-Status} ${Version}\n' 2>/dev/null | awk '$2 == "installed" {print $1 " " $3}' | sort

sec "files"
# le bruit qui bouge tout seul (journaux, caches de tiers, historique du shell) est filtré ; ce qui porte « golem »
# ne l'est JAMAIS, même dans un dossier filtré
$S find "$HOME" /etc /usr/local /opt -xdev \( -type f -o -type l -o -type d \) -printf '%y %p\n' 2>/dev/null \
  | grep -Ev "^. $HOME/\.(bash_history|lesshst|viminfo|sudo_as_admin_successful|wget-hsts|python_history)$" \
  | grep -Ev "^. $HOME/\.(cache|local/state|config/pulse|local/share/(recently-used|Trash))(/|$)" \
  | grep -Ev '^. /etc/(ld\.so\.cache|machine-id|resolv\.conf|mtab|adjtime|\.pwd\.lock|subuid-|subgid-|(passwd|group|shadow|gshadow)-)$' \
  | grep -Ev '^. /etc/(ssl/certs|alternatives|apparmor\.d/cache)(/|$)' \
  | grep -Ev "^. $HOME/golem-src(/|\$)" \
  | sort
$S find "$HOME/.cache" /tmp /dev/shm -maxdepth 1 -iname '*golem*' -printf '%y %p\n' 2>/dev/null | sort

sec "units"
systemctl list-unit-files --state=enabled,masked --no-legend 2>/dev/null | awk '{print "system " $1 " " $2}' | sort
systemctl --user list-unit-files --state=enabled,masked --no-legend 2>/dev/null | awk '{print "user " $1 " " $2}' | sort

sec "identity"
echo "groups $(id -nG | tr ' ' '\n' | sort | tr '\n' ' ')"
echo "linger $(loginctl show-user "$USER" -p Linger --value 2>/dev/null)"
echo "governor $(cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor 2>/dev/null || echo none)"
echo "sysctl ip_unprivileged_port_start $(sysctl -n net.ipv4.ip_unprivileged_port_start 2>/dev/null)"

sec "firewall"
$S ufw status 2>/dev/null || echo "ufw absent"

sec "network"
nmcli -t -f NAME connection show 2>/dev/null | sort || echo "nmcli absent"

sec "reaper.ini"
# les clés seules, pas les valeurs qui bougent à chaque lancement (fenêtres, dernières sessions)
[ -f "$HOME/.config/REAPER/reaper.ini" ] && grep -E '^(csurf|midiin|midiout|automute|norunmute|alsa_|linux_audio)' "$HOME/.config/REAPER/reaper.ini" | sort
exit 0
