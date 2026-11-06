#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — la BOÎTE DÉDIÉE : `golem server` au boot, sans session ouverte (docs/installer.md §4).
#
#   ./provision/autostart/install-autostart.sh         active (= `golem autostart on`)
#   ./provision/autostart/install-autostart.sh --off   désactive (= `golem autostart off`)
#
# Un service systemd UTILISATEUR (golem-server.service) + linger : systemd démarre les services de
# l'utilisateur au boot, sans qu'il se connecte. Reaper part sur Xvfb (provision/start.sh) : il ne
# faut ni écran ni session graphique.
#
# 2026-10-16 (docs/installer.md §4) : ce script NE DURCIT PLUS RIEN. Le gouverneur CPU permanent (golem-perf.service)
# est parti avec harden.sh, dans le geste séparé « Lock down this machine » (System ▸ Dashboard) — démarrer avec
# l'ordinateur ne touche jamais au reste de la machine. Le même script sert `golem autostart on|off` et l'interrupteur
# « Start golem with this computer » de l'app (bridge/machine.py), lancé SANS terminal : le linger se pose d'abord
# sans sudo (logind le permet à l'utilisateur d'une session active), puis par `sudo -n`, sinon on le dit.
#
# 2026-10-06 : remplace l'ancien kiosque (LightDM autologin + Openbox + Chromium plein écran sur
# l'écran local), abandonné : un GoleM sans fenêtre se pilote depuis une tablette. Une machine qui
# avait l'ancien kiosque en est nettoyée ici (unités, autostart Openbox, autologin LightDM).
# Idempotent : rejouable sans casser.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
UNITS="$HOME/.config/systemd/user"
log() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
# sudo sans prompt si possible (installateur graphique : askpass ; NOPASSWD) ; sinon il demande
SUDO="sudo"; sudo -n true 2>/dev/null && SUDO="sudo -n"
. "$ROOT/provision/lib-receipt.sh"      # reçu d'install (docs/uninstall.md §2)
# le linger est-il posé ? (le fichier de logind EST l'état — loginctl n'en est que la lecture)
linger_on() { [ -e "/var/lib/systemd/linger/$USER" ]; }
# poser / retirer le linger : sans sudo d'abord (polkit l'accorde à l'utilisateur d'une session active), puis $SUDO.
# Jamais d'invite : lancé par l'app, il n'y a personne au terminal.
linger_set() {   # $1 = enable | disable
  if [ "$1" = enable ]; then
    loginctl enable-linger "$USER" 2>/dev/null || $SUDO loginctl enable-linger "$USER" </dev/null 2>/dev/null
  else
    loginctl disable-linger "$USER" 2>/dev/null || $SUDO loginctl disable-linger "$USER" </dev/null 2>/dev/null
  fi
}

if [ "${1:-}" = "--off" ]; then
  log "Autostart golem : désactivation"
  systemctl --user disable golem-server.service 2>/dev/null || true
  rm -f "$UNITS/golem-server.service"
  systemctl --user daemon-reload
  # le linger revient à sa valeur d'AVANT golem (docs/uninstall.md §8) : retiré seulement si le reçu dit qu'il
  # n'était pas là. Sans reçu (install d'avant lui), on ne sait pas : on le laisse, comme avant.
  prior_linger="$(python3 "$ROOT/provision/receipt.py" get linger 2>/dev/null || true)"
  if [ "$prior_linger" = false ] && linger_on; then
    if linger_set disable; then echo "✓ linger retiré (il n'était pas posé avant golem)"
    else echo "⚠ linger non retiré (sudo) : loginctl disable-linger $USER"; fi
  elif [ "$prior_linger" = true ]; then
    echo "· linger gardé : il était posé avant golem"
  fi
  echo "✓ golem ne démarre plus avec la machine."
  exit 0
fi

# ── l'ANCIEN kiosque, s'il est là (rack installé avant 2026-10-06) ─────────────────────────────
# On DÉSACTIVE sans --now : arrêter ces unités couperait un GoleM peut-être en train de jouer.
OLD=(golem-kiosk.service golem-reaper.service golem-midi.service golem-bridge.service golem.target)
if ls "$UNITS"/golem-kiosk.service "$UNITS"/golem.target >/dev/null 2>&1; then
  log "Ancien kiosque : retrait (unités, autostart Openbox, autologin LightDM)"
  for u in "${OLD[@]}"; do
    systemctl --user disable "$u" 2>/dev/null || true
    rm -f "$UNITS/$u"
  done
  # l'autostart Openbox n'est retiré que s'il est le NÔTRE (il lançait golem.target)
  grep -q "golem.target" "$HOME/.config/openbox/autostart" 2>/dev/null && rm -f "$HOME/.config/openbox/autostart"
  $SUDO rm -f /etc/lightdm/lightdm.conf.d/50-golem.conf || echo "⚠ autologin LightDM non retiré (sudo) : /etc/lightdm/lightdm.conf.d/50-golem.conf"
fi

log "Service golem-server (au boot, sans session)"
# linger : les services de l'utilisateur démarrent au boot, sans login
# reçu : le linger d'AVANT (le premier passage gagne) — `autostart off` et la désinstallation y reviennent
if linger_on; then receipt prior linger true; else receipt prior linger false; fi
if ! linger_on && ! linger_set enable; then
  # sans linger, golem ne partirait qu'à la connexion : on ne pose rien et on le dit (l'app affiche cette ligne)
  echo "✗ could not let golem start without a sign-in (loginctl enable-linger $USER was refused) — run: golem autostart on, in a terminal"
  exit 3
fi
install -d "$UNITS"
sed "s#@ROOT@#$ROOT#g" "$HERE/units/golem-server.service" > "$UNITS/golem-server.service"
receipt_add "$UNITS/golem-server.service" file golem
systemctl --user daemon-reload
systemctl --user enable golem-server.service

log "Préflight"
command -v Xvfb >/dev/null 2>&1 || echo "⚠ Xvfb absent — sans écran, Reaper ne pourra pas démarrer (sudo apt install xvfb)"
[ -d "$ROOT/.venv" ]                || echo "⚠ venv bridge absent — provision/bridge-setup.sh ?"
[ -f "$ROOT/sets/golem-set.rpp" ]   || echo "⚠ projet Set absent (sets/golem-set.rpp)"
id -nG | grep -qw audio             || echo "⚠ $USER n'est pas dans le groupe audio — sans session, la carte son lui sera refusée"

cat <<'MSG'
✅ golem démarrera avec la machine, sans fenêtre et sans login.
   Au prochain boot : ouvre l'adresse de golem sur ta tablette (golem status pour la voir).
   Démarrer maintenant :  systemctl --user start golem-server
   Journaux :            journalctl --user -u golem-server · /tmp/golem-bridge.log · /tmp/golem-reaper.log
   Désactiver :          golem autostart off
MSG
