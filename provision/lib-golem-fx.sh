#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# LE RATTRAPAGE DE golem-fx APRÈS UNE MISE À JOUR (docs/update.md §3 bis, 2026-11-22). Settings ▸ About ▸ Update pose le
# code d'une release, pas ses plugins : un golem installé avant golem-fx (v0.6.4) gardait ses anciens plugins sous une
# usine refaite sur golem-fx, et les blocs que seul golem-fx joue restaient hors du son. reload.sh (la relance d'après
# mise à jour) et start.sh appellent ceci AVANT que REAPER ne démarre : il scanne ~/.vst3 à son lancement.
#   golem_fx_catch_up <racine de golem>   -> 0 si des plugins viennent d'être posés, 1 sinon
# Jamais fatal, jamais bloquant : rien si un bundle est déjà là (release ou build de dev), rien sans réseau (une sonde
# de 5 s — un golem hors ligne sur scène ne doit pas attendre un téléchargement), et un échec se réessaie au prochain
# démarrage. GOLEM_FX_CATCH_UP=0 le coupe (bancs, tests).
golem_fx_catch_up() {
  local here="$1"
  [ "${GOLEM_FX_CATCH_UP:-1}" = 0 ] && return 1
  python3 "$here/provision/golem_fx.py" --needed >/dev/null 2>&1 || return 1
  if ! curl -fsI --max-time 5 https://github.com >/dev/null 2>&1; then
    echo "→ golem-fx : pas encore posé, et pas de réseau — nouvel essai au prochain démarrage"
    return 1
  fi
  echo "→ golem-fx : les effets de golem ne sont pas sur cette machine — installation…"
  if "$here/provision/install-golem-fx.sh"; then
    return 0
  fi
  echo "⚠ golem-fx non posé — les blocs gardent leurs plugins d'origine ; nouvel essai au prochain démarrage"
  return 1
}
