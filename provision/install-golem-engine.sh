#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Le Golem Engine (le moteur audio de golem, GPL) sous Linux : le paquet autonome publié sur Goldoralf/golem-binaries,
# épinglé dans provision/downloads.sha256 (fetch_verified le refuse si son empreinte change), posé dans
# ~/opt/golem-engine sans sudo — provision/golem_engine.py (pose atomique, reçu d'install). TOUJOURS installé, que
# REAPER soit coché ou non (docs/install-v2.md §1).
# Rend 1 si la pose échoue (téléchargement, empreinte, pas de build pour cette architecture) : install.sh le dit
# (soft_fail) et continue — golem tourne alors sur REAPER s'il est là. Rend 2 tant qu'aucune release n'est épinglée.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/lib-fetch.sh"
case "$(uname -m)" in
  x86_64) ;;
  *) echo "  ⚠ Golem Engine : pas de build pour $(uname -m)"; exit 1 ;;
esac
URL="$(python3 -c 'import sys; sys.path.insert(0, sys.argv[1]); import golem_engine as G; print(G.asset_url() if G.VERSION else "")' "$HERE")"
# 2 = « pas encore de release » : ce n'est pas une panne, install.sh ne propose pas de réessayer
if [ -z "$URL" ]; then echo "  · Golem Engine : aucune release épinglée pour l'instant"; exit 2; fi
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
echo "  ↓ Golem Engine (précompilé, golem-binaries)"
fetch_verified "$URL" "$tmp/engine.tar.gz" || exit 1
python3 "$HERE/golem_engine.py" --place "$tmp/engine.tar.gz"

# le verrou mémoire du moteur (provision/golem-mlock.c, system-tuning.md « Engine memory ») : sans gcc, le moteur tourne
# quand même, il peut seulement partir en swap
. "$HERE/lib-receipt.sh"
shim="$HOME/.local/lib/golem/libgolem-mlock.so"
if command -v gcc >/dev/null 2>&1; then
  ex=$(receipt_existed "$shim")
  mkdir -p "$(dirname "$shim")"
  if gcc -O2 -shared -fPIC -o "$shim" "$HERE/golem-mlock.c"; then
    # shellcheck disable=SC2086
    receipt_add "$shim" file golem $ex
    echo "  ✓ Golem Engine : mémoire verrouillée (libgolem-mlock)"
  else
    echo "  ⚠ Golem Engine : verrou mémoire non compilé — le moteur peut partir en swap"
  fi
else
  echo "  ⚠ Golem Engine : gcc absent, verrou mémoire non compilé — le moteur peut partir en swap"
fi
