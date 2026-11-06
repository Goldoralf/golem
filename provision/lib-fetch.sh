# shellcheck shell=bash
# SPDX-License-Identifier: GPL-3.0-or-later
# TÉLÉCHARGER UN BINAIRE QU'ON VA EXÉCUTER (audit 2026-10-15, lot 5) : chaque URL est épinglée dans
# provision/downloads.sha256 (« <sha256>  <url> », une ligne par fichier) et le fichier n'est GARDÉ que si son
# empreinte correspond. Une URL absente de la table est REFUSÉE — GOLEM_ALLOW_UNPINNED=1 pour passer outre, en le
# sachant. Monter une version = changer l'URL dans le script ET ajouter sa ligne ici (sha256sum du fichier officiel).
#   . "$(dirname "$0")/lib-fetch.sh" ; fetch_verified "$url" "$dest"
GOLEM_SUMS="${GOLEM_SUMS:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/downloads.sha256}"

fetch_verified() {
  local url="$1" dest="$2" want got
  want=$(awk -v u="$url" '$1 !~ /^#/ && $2 == u { print $1; exit }' "$GOLEM_SUMS" 2>/dev/null || true)
  if [ -z "$want" ] && [ "${GOLEM_ALLOW_UNPINNED:-0}" != 1 ]; then
    echo "    ✗ non épinglé dans provision/downloads.sha256 — refusé : $url" >&2
    echo "      (GOLEM_ALLOW_UNPINNED=1 pour l'accepter sans vérification)" >&2
    return 1
  fi
  if ! curl -fL --retry 3 -sS "$url" -o "$dest.part"; then
    rm -f "$dest.part"; echo "    ✗ téléchargement échoué : $url" >&2; return 1
  fi
  if [ -n "$want" ]; then
    got=$(sha256sum "$dest.part" | cut -d' ' -f1)
    if [ "$got" != "$want" ]; then
      rm -f "$dest.part"
      echo "    ✗ EMPREINTE FAUSSE — fichier rejeté : $url" >&2
      echo "      attendu $want, reçu $got" >&2
      return 1
    fi
  fi
  mv "$dest.part" "$dest"
}
