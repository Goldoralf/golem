#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — wrapper réseau (docs/network.md). SEULE surface sudo du réseau :
# le bridge n'appelle JAMAIS nmcli direct pour muter ; il passe par
#   sudo /usr/local/sbin/golem-net <verbe> [args]
# (copie root-owned installée par setup-net-sudo.sh — un script user-writable
# en NOPASSWD serait une escalade triviale).
#
# Verbes MUTANTS (root) :
#   join <ssid> [psk]   rejoindre un réseau (crée/active le profil station)
#   up <name>           réactiver un profil connu
#   down <name>         couper un profil
#   forget <name>       oublier un profil
#   ap-up               lever l'AP « golem » (profil golem-ap, config network.json)
#   ap-down             couper l'AP
#   boot-fallback       machine à états du boot : station connue < timeout sinon AP
# Verbes LECTURE (pas besoin de root — le bridge peut aussi appeler nmcli direct) :
#   status | scan | known | leases
set -euo pipefail

# racine du repo : baked à l'install (@ROOT@), surchageable en dev
GOLEM_ROOT="${GOLEM_ROOT:-@ROOT@}"
[ -d "$GOLEM_ROOT" ] || GOLEM_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CFG="$GOLEM_ROOT/config/network.json"

die() { echo "✗ $*" >&2; exit 1; }

# --- validation stricte des entrées (whitelist, pas d'option-injection) -------
valid_ssid() {  # 1..32 chars imprimables, pas de tiret initial (option-injection nmcli)
  local s="$1"
  [ -n "$s" ] && [ "${#s}" -le 32 ] || return 1
  case "$s" in -*) return 1 ;; esac
  LC_ALL=C printf '%s' "$s" | grep -qE '^[[:print:]]+$'
}
valid_psk() {   # WPA2 : 8..63 chars imprimables
  local p="$1"
  [ "${#p}" -ge 8 ] && [ "${#p}" -le 63 ] || return 1
  LC_ALL=C printf '%s' "$p" | grep -qE '^[[:print:]]+$'
}
valid_name() {  # nom de profil NM : comme un SSID (nos profils portent le nom du SSID)
  valid_ssid "$1"
}

cfg() {  # cfg <jq-expr> <défaut>
  [ -f "$CFG" ] && jq -re "$1 // empty" "$CFG" 2>/dev/null || true
}

wifi_dev() {  # 1er device wifi géré par NM
  nmcli -t -f DEVICE,TYPE device status | awk -F: '$2=="wifi"{print $1; exit}'
}

# LE NOM DU RACK SUR LE POINT D'ACCÈS (docs/connect.md, lot R2 — 2026-09-16). En mode `shared`, le dnsmasq
# de NetworkManager répond au DNS des téléphones connectés et lit /etc/NetworkManager/dnsmasq-shared.d/.
# On y sert `<machine>.local` ⇒ 10.42.0.1 : un téléphone qui n'interroge pas mDNS (certains Android)
# résout quand même le nom sous lequel il a rangé son jeton à la répète. À VALIDER SUR LE RACK.
ap_name_dns() {
  local host dir=/etc/NetworkManager/dnsmasq-shared.d
  host="$(hostname -s 2>/dev/null || true)"
  LC_ALL=C printf '%s' "$host" | grep -qE '^[A-Za-z0-9][A-Za-z0-9-]{0,62}$' || { echo "⚠ nom de machine inutilisable pour le DNS de l'AP : « $host »" >&2; return 0; }
  mkdir -p "$dir"
  # + `golem.local` (2026-10-03) : LE nom commun du rack et du poste Windows/macOS, annoncé aussi en mDNS
  # par le bridge (bridge/reach.py) — servi ici pour les téléphones qui n'interrogent pas mDNS
  printf '# GoleM (docs/connect.md R2) — écrit par golem-net ap-up, ne pas éditer\naddress=/%s.local/10.42.0.1\naddress=/golem.local/10.42.0.1\n' "$host" > "$dir/golem-name.conf"
}

ap_ensure_profile() {
  local ssid psk band dev
  ap_name_dns
  ssid="$(cfg '.ap.ssid')"; ssid="${ssid:-golem}"   # la marque s'écrit golem (2026-10-06)
  psk="$(cfg '.ap.psk')"
  band="$(cfg '.ap.band')"; band="${band:-bg}"
  dev="$(wifi_dev)"; [ -n "$dev" ] || die "aucune radio WiFi gérée par NetworkManager"
  valid_ssid "$ssid" || die "SSID AP invalide dans network.json"
  [ -n "$psk" ] || die "pas de mot de passe AP dans config/network.json (.ap.psk) — AP ouvert refusé"
  valid_psk "$psk" || die "mot de passe AP invalide (8-63 caractères)"

  if nmcli -t -f NAME connection show | grep -qxF golem-ap; then
    nmcli connection modify golem-ap 802-11-wireless.ssid "$ssid" \
      802-11-wireless.band "$band" wifi-sec.psk "$psk" >/dev/null
  else
    nmcli connection add type wifi ifname "$dev" con-name golem-ap autoconnect no \
      ssid "$ssid" 802-11-wireless.mode ap 802-11-wireless.band "$band" \
      ipv4.method shared wifi-sec.key-mgmt wpa-psk wifi-sec.psk "$psk" >/dev/null
  fi
}

case "${1:-}" in
  # --- lecture ----------------------------------------------------------------
  status)  nmcli -t -f DEVICE,TYPE,STATE,CONNECTION device status ;;
  scan)    nmcli -t -f IN-USE,SSID,SIGNAL,SECURITY device wifi list --rescan yes ;;
  known)   nmcli -t -f NAME,TYPE,AUTOCONNECT connection show ;;
  leases)  cat /var/lib/NetworkManager/dnsmasq-*.leases 2>/dev/null || true ;;

  # --- mutation ---------------------------------------------------------------
  join)
    ssid="${2:-}"; psk="${3:-}"
    valid_ssid "$ssid" || die "SSID invalide"
    if [ -n "$psk" ]; then
      valid_psk "$psk" || die "mot de passe invalide (8-63 caractères)"
      nmcli device wifi connect "$ssid" password "$psk"
    else
      nmcli device wifi connect "$ssid"
    fi
    ;;
  up)     valid_name "${2:-}" || die "nom de profil invalide"; nmcli connection up "$2" ;;
  down)   valid_name "${2:-}" || die "nom de profil invalide"; nmcli connection down "$2" ;;
  forget) valid_name "${2:-}" || die "nom de profil invalide"
          [ "$2" = golem-ap ] && die "golem-ap ne s'oublie pas (ap-down pour le couper)"
          nmcli connection delete "$2" ;;
  ap-up)   ap_ensure_profile; nmcli connection up golem-ap ;;
  ap-down) nmcli connection down golem-ap 2>/dev/null || true ;;

  boot-fallback)
    # Machine à états du boot (docs/network.md) : si aucun réseau connu
    # n'accroche avant le timeout → lever l'AP. Ethernet vit sa vie à côté.
    timeout="$(cfg '.fallback_timeout_s')"; timeout="${timeout:-30}"
    for i in $(seq 1 "$timeout"); do
      if nmcli -t -f DEVICE,TYPE,STATE device status | grep -q '^[^:]*:wifi:connected'; then
        echo "✓ station connectée — pas d'AP"
        exit 0
      fi
      sleep 1
    done
    echo "→ aucun réseau connu après ${timeout}s — AP de secours"
    ap_ensure_profile
    nmcli connection up golem-ap
    echo "✓ AP levé (10.42.0.1)"
    ;;

  *)
    grep -E '^#   [a-z]' "$0" | sed 's/^#   //'
    exit 1
    ;;
esac
