#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Lie la config Reaper PORTABLE du repo dans ~/.config/REAPER.
# Deux stratégies, selon que Reaper pollue le dossier ou non :
#   - FXChains : symlink du dossier entier (Reaper n'y dépose rien ; nos "Save chain" y atterrissent).
#   - Scripts  : Reaper y déverse ~450 scripts d'usine → on ne symlinke QU'UN sous-dossier
#                `golem/` pour NOS scripts, en gardant le dossier Scripts réel hors repo.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_REAPER="$(cd "$HERE/../reaper" && pwd)"
DEST="${HOME}/.config/REAPER"
mkdir -p "$DEST"
. "$HERE/lib-receipt.sh"

# Ce qui est À L'UTILISATEUR à l'endroit d'un de nos liens est mis de côté sous un nom À NOUS (*.golem-orig,
# jamais .bak : un .bak de l'utilisateur ne doit pas passer pour le nôtre), et le reçu dit où — la
# désinstallation le remet en place (docs/uninstall.md §2). Un ancien `.bak` posé par golem reste tel quel.
# À l'utilisateur = un vrai fichier/dossier, ou un lien qui ne vise pas un dépôt golem (…/reaper/<rel>).
MOVED=""
set_aside() {   # $1 = destination du lien, $2 = chemin relatif attendu dans le dépôt (reaper/…)
  MOVED=""
  if [ -L "$1" ]; then
    case "$(readlink "$1")" in */"$2") return 0 ;; esac
  elif [ ! -e "$1" ]; then
    return 0
  fi
  local orig="$1.golem-orig"
  if [ -e "$orig" ] || [ -L "$orig" ]; then orig="$1.golem-orig.$(date +%Y%m%d-%H%M%S)"; fi
  echo "  ⚠ $1 existe (à toi) — mis de côté en $orig"
  mv "$1" "$orig"
  MOVED="$orig"
}
link() {   # $1 = source, $2 = destination, $3 = relatif attendu (reaper/…)
  set_aside "$2" "$3"
  ln -sfn "$1" "$2"
  if [ -n "$MOVED" ]; then receipt_add "$2" link reaper-links --moved-to "$MOVED"
  else receipt_add "$2" link reaper-links; fi
}

# FXChains : dossier entier
src="$REPO_REAPER/FXChains"; dst="$DEST/FXChains"
link "$src" "$dst" reaper/FXChains
echo "  $dst → $src"

# Scripts : sous-dossier namespacé (le dossier Scripts réel reste hors repo)
mkdir -p "$DEST/Scripts"
link "$REPO_REAPER/Scripts" "$DEST/Scripts/golem" reaper/Scripts
echo "  $DEST/Scripts/golem → $REPO_REAPER/Scripts  (scripts d'usine Cockos restent hors repo)"

# Effects (JSFX) : sous-dossier namespacé (Reaper déverse ses JSFX d'usine dans Effects/)
mkdir -p "$DEST/Effects"
link "$REPO_REAPER/Effects" "$DEST/Effects/golem" reaper/Effects
echo "  $DEST/Effects/golem → $REPO_REAPER/Effects  (JSFX GoleM, ex. accordeur)"

# __startup.lua : Reaper l'exécute au démarrage → lance le veilleur tout seul (zéro action user)
startup_src="$REPO_REAPER/Scripts/__startup.lua"; startup_dst="$DEST/Scripts/__startup.lua"
link "$startup_src" "$startup_dst" reaper/Scripts/__startup.lua
echo "  $startup_dst → $startup_src  (auto-lance le veilleur)"

# OSC : on lie chaque .ReaperOSC dans le dossier OSC de Reaper (apparaît dans Preferences/Control)
mkdir -p "$DEST/OSC"
for osc in "$REPO_REAPER"/OSC/*.ReaperOSC; do
  [ -e "$osc" ] || continue
  link "$osc" "$DEST/OSC/$(basename "$osc")" "reaper/OSC/$(basename "$osc")"
  echo "  $DEST/OSC/$(basename "$osc") → $osc"
done

echo "Config Reaper portable liée. (OSC : ajouter le device dans Preferences/Control — cf. golem.ReaperOSC.)"
