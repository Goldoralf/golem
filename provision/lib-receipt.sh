# shellcheck shell=bash
# SPDX-License-Identifier: GPL-3.0-or-later
# LE REÇU D'INSTALLATION depuis un script bash (docs/uninstall.md §2) — une enveloppe de provision/receipt.py :
#   . "$(dirname "${BASH_SOURCE[0]}")/lib-receipt.sh"
#   receipt_add PATH KIND GROUP [--owner root] [--moved-to ORIG] [--existed]
#   receipt prior KEY VALUE · receipt apt-snapshot before|after · receipt deb NAME
#   receipt apt-requested PKG…   (les paquets NOMMÉS à apt-get install / dpkg -i : les explicites, §2)
# Le helper est appelé avec le python3 SYSTÈME (le venv n'existe pas encore) et son échec ne casse JAMAIS
# l'installation : on le dit sur stderr, on continue. `--by` est le chemin du script appelant, relatif au dépôt.
GOLEM_RECEIPT_PY="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/receipt.py"
if [ -z "${GOLEM_RECEIPT_BY:-}" ]; then
  _rcpt_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
  _rcpt_src="$(cd "$(dirname "${BASH_SOURCE[1]:-$0}")" && pwd)/$(basename "${BASH_SOURCE[1]:-$0}")"
  GOLEM_RECEIPT_BY="${_rcpt_src#"$_rcpt_root"/}"
  unset _rcpt_root _rcpt_src
fi

receipt() {
  python3 "$GOLEM_RECEIPT_PY" "$@" >/dev/null || echo "  ⚠ install receipt not updated ($1 ${2:-})" >&2
  return 0
}

receipt_add() {   # chemin kind groupe [options de receipt.py add…]
  local path="$1" kind="$2" group="$3"; shift 3
  receipt add "$path" --kind "$kind" --group "$group" --by "$GOLEM_RECEIPT_BY" "$@"
}

# « --existed » si le chemin est déjà là — à appeler AVANT de le poser : `ex=$(receipt_existed "$dst")`
receipt_existed() { if [ -e "$1" ] || [ -L "$1" ]; then echo --existed; fi; }

# un chemin du home écrit avec `~` (pour une valeur `prior`, que receipt.py ne réécrit pas)
receipt_tilde() { case "$1" in "$HOME"|"$HOME"/*) echo "~${1#"$HOME"}" ;; *) echo "$1" ;; esac; }
