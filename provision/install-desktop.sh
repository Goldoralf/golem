#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — installation DESKTOP (workstation Linux) : pose la commande `golem` dans le PATH.
# À lancer UNE fois après provision/install.sh :   ./provision/install-desktop.sh
# (Démarrer avec la machine : System ▸ Dashboard, ou `golem autostart on` — golem server au boot, sans session.)
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$HOME/.local/bin"
. "$HERE/provision/lib-receipt.sh"      # reçu d'install (docs/uninstall.md §2)
mkdir -p "$BIN"
chmod +x "$HERE/provision/golem"
ln -sf "$HERE/provision/golem" "$BIN/golem"
receipt_add "$BIN/golem" link golem
echo "✓ commande installée : $BIN/golem -> provision/golem"

# ── lanceur de bureau (menu/dock) ────────────────────────────────────────────
# Chemin ABSOLU dans Exec : un lanceur graphique n'hérite pas forcément du PATH du shell
# (c'est le piège classique — ça marche au terminal et pas depuis le menu).
APPS="$HOME/.local/share/applications"
# 512x512 : une taille que le thème hicolor DÉCLARE (index.theme). Un dossier 180x180 n'y figure pas :
# GNOME ne regarde jamais dedans et le lanceur montrait la roue par défaut (posé jusqu'au 2026-10-26).
ICONS="$HOME/.local/share/icons/hicolor/512x512/apps"
OLD_ICONS="$HOME/.local/share/icons/hicolor/180x180/apps"
mkdir -p "$APPS" "$ICONS"
install -m644 "$HERE/app/icons/icon-512.png" "$ICONS/golem.png"
if [ -f "$OLD_ICONS/golem.png" ]; then
  rm -f "$OLD_ICONS/golem.png"
  rmdir "$OLD_ICONS" "${OLD_ICONS%/apps}" 2>/dev/null || true
fi
sed -e "s|^Exec=golem$|Exec=$BIN/golem|" \
    -e "s|^Exec=golem desktop$|Exec=$BIN/golem desktop|" \
    -e "s|^Exec=golem server$|Exec=$BIN/golem server|" \
    -e "s|^Exec=golem stop$|Exec=$BIN/golem stop|" \
    "$HERE/provision/golem.desktop" > "$APPS/golem.desktop"
chmod 644 "$APPS/golem.desktop"
receipt_add "$ICONS/golem.png" file golem
receipt_add "$APPS/golem.desktop" file golem
# « Uninstall golem » (docs/uninstall.md §4) : à côté du lanceur, noté dans le reçu comme lui. Le moteur le
# retrouve aussi par son nom (golem*.desktop) quand il n'y a pas de reçu.
cat > "$APPS/golem-uninstall.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Uninstall golem
Comment=Back up your sounds and settings, then remove golem from this computer
Exec=$BIN/golem uninstall
Icon=golem
Terminal=false
Categories=AudioVideo;Audio;
EOF
chmod 644 "$APPS/golem-uninstall.desktop"
receipt_add "$APPS/golem-uninstall.desktop" file golem
# le profil de navigateur du lanceur (provision/golem : APPDIR) naît à la première fenêtre — noté dès maintenant
receipt_add "${XDG_DATA_HOME:-$HOME/.local/share}/golem/browser" dir golem
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS" 2>/dev/null || true
command -v gtk-update-icon-cache   >/dev/null 2>&1 && gtk-update-icon-cache -f -t "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
echo "✓ lanceur installé : $APPS/golem.desktop (clic droit → « server » / « stop ») + « Uninstall golem »"

# ── Xvfb : ce qui permet à `golem desktop` de n'ouvrir QU'UNE fenêtre ────────────────────
# Il est dans provision/packages.txt (donc posé par install.sh), mais ce script se lance aussi
# seul sur un poste déjà provisionné : sans le contrôle, l'utilisateur découvrirait Reaper à
# l'écran sans comprendre pourquoi. On le DIT, on ne le corrige pas en douce.
if command -v Xvfb >/dev/null 2>&1; then
  echo "✓ Xvfb présent — Reaper sera masqué (golem desktop --dev pour le voir)"
else
  echo "⚠ Xvfb absent — Reaper s'ouvrira À L'ÉCRAN, en plus de la fenêtre GoleM."
  echo "  Pour n'avoir qu'une fenêtre :  sudo apt install xvfb x11-utils"
fi

case ":$PATH:" in
  *":$BIN:"*) echo "✓ ~/.local/bin est dans le PATH — tape : golem" ;;
  *) echo "⚠ ajoute ~/.local/bin à ton PATH (ex. dans ~/.bashrc) : export PATH=\"\$HOME/.local/bin:\$PATH\"" ;;
esac
