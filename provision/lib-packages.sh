# shellcheck shell=bash
# SPDX-License-Identifier: GPL-3.0-or-later
# LA LISTE DES PAQUETS APT (provision/packages.txt) — lue ici, par install.sh et par les tests :
#   . "$(dirname "${BASH_SOURCE[0]}")/lib-packages.sh"
#   golem_packages_parse FICHIER      → « nom<TAB>req|opt », un paquet par ligne
#   golem_packages_resolve FICHIER    → remplit PKGS (installables), PKGS_SKIPPED (optionnels absents),
#                                       PKGS_MISSING (essentiels absents)
# Un nom suffixé « ? » est OPTIONNEL (`calf-plugins?`) : absent de la distribution, il est écarté et dit ;
# un essentiel absent reste FATAL (c'est à install.sh de mourir en le nommant).
# Pourquoi (Ubuntu 26.04, 2026-11-03) : invada-studio-plugins-lv2 a quitté la distribution ; l'unique
# `apt-get install` de toute la liste mourait sur lui, et l'install entière avec, dès la phase 1.
# ⚠ À appeler APRÈS `apt-get update` : le candidat se lit dans l'index.

golem_packages_parse() {
  # commentaires pleine ligne ET inline retirés, puis un « ? » final marque l'optionnel
  sed 's/#.*//' "$1" | awk 'NF { n = $1; k = "req"; if (n ~ /\?$/) { sub(/\?$/, "", n); k = "opt" } print n "\t" k }'
}

golem_apt_candidate() {
  # « Candidate: (none) » (connu, sans version installable) ou sortie VIDE (inconnu de l'index) : les deux = absent.
  # Pas de `exit` dans awk : sortir tôt ferait prendre SIGPIPE à apt-cache, et pipefail en ferait un échec
  # (docs/pitfalls/install.md, « SIGPIPE under pipefail »). LC_ALL=C : sinon « Candidat : » en français.
  LC_ALL=C apt-cache policy "$1" 2>/dev/null | awk '$1 == "Candidate:" { c = $2 } END { print c }' || true
}

golem_packages_resolve() {
  PKGS=(); PKGS_SKIPPED=(); PKGS_MISSING=()
  local name kind cand
  while IFS=$'\t' read -r name kind; do
    cand="$(golem_apt_candidate "$name")"
    if [ -n "$cand" ] && [ "$cand" != "(none)" ]; then PKGS+=("$name")
    elif [ "$kind" = opt ]; then PKGS_SKIPPED+=("$name")
    else PKGS_MISSING+=("$name")
    fi
  done < <(golem_packages_parse "$1")
}

golem_chromium_deb() {
  # Le Chromium en VRAI paquet apt, s'il y en a un : « chromium » de Debian, ou celui que Mint construit (2026-11-03).
  # Mint bloque snapd (nosnap.pref), Debian et Pop n'ont pas snap : sans ce chemin, pas de fenêtre golem, un onglet.
  # Sous Ubuntu, `chromium`/`chromium-browser` ne sont que des RENVOIS vers le snap (ils dépendent de snapd) : écartés,
  # c'est alors le snap qu'on pose. Rend le nom, ou rien.
  local cand
  cand="$(golem_apt_candidate chromium)"
  [ -n "$cand" ] && [ "$cand" != "(none)" ] || return 0
  # même règle que golem_apt_candidate : pas de sortie précoce dans le tube (SIGPIPE sous pipefail)
  if LC_ALL=C apt-cache depends chromium 2>/dev/null | awk '$2 == "snapd" { s = 1 } END { exit !s }'; then
    return 0
  fi
  echo chromium
}
