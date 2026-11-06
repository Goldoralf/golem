#!/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — ce qui s'installe en ADMINISTRATEUR sous macOS (docs/platforms.md, 2026-10-04).
# Le pendant de provision/windows/install-system.ps1 : lancé UNE fois par installer/platform_macos.py
# derrière la fenêtre d'administrateur de macOS (osascript « with administrator privileges »).
#
#   install-system.sh --log FICHIER [--reaper] [--nam] [--avldrums] [--sfizz] [--vitalium] [--dragonfly] [--proteus]
#
# Chaque fichier vient de provision/macos/pins.json (adresse ET empreinte) : une empreinte qui ne
# correspond pas ARRÊTE l'étape, on ne pose pas un binaire que personne n'a vérifié. Écrit SANS Mac :
# la recette (docs/private/recette-macos.md §1) est la première fois qu'il tourne.
# Le journal est en anglais : l'installateur l'affiche tel quel (CLAUDE.md, règle 4).
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
PINS="$HERE/pins.json"
LOG=/dev/stdout
DO_REAPER=0; DO_NAM=0; DO_AVL=0; DO_SFIZZ=0; DO_VITALIUM=0; DO_DRAGONFLY=0; DO_PROTEUS=0
while [ $# -gt 0 ]; do
  case "$1" in
    --log) LOG="$2"; shift ;;
    --reaper) DO_REAPER=1 ;;
    --nam) DO_NAM=1 ;;
    --avldrums) DO_AVL=1 ;;
    --sfizz) DO_SFIZZ=1 ;;
    --vitalium) DO_VITALIUM=1 ;;
    --dragonfly) DO_DRAGONFLY=1 ;;
    --proteus) DO_PROTEUS=1 ;;
    *) echo "unknown option $1" >>"$LOG"; exit 2 ;;
  esac
  shift
done
exec >>"$LOG" 2>&1

# sur la sortie d'ERREUR (= le journal) : fetch rend son chemin sur la sortie standard, capturée par $(…)
say() { printf '▶ %s\n' "$*" >&2; }
ok() { printf '✓ %s\n' "$*" >&2; }
fail() { printf '✗ %s\n' "$*" >&2; exit 1; }
# plutil lit le JSON depuis macOS 12 : aucun Python (celui de /usr/bin n'est qu'un stub sans Xcode)
pin() { /usr/bin/plutil -extract "$1" raw -o - "$PINS" 2>/dev/null; }

DL="/Library/Caches/GoleM/installers"
mkdir -p "$DL"

fetch() {   # fetch <clé de pins.json> -> chemin du fichier vérifié
  local key="$1" url sha file got
  url="$(pin "$key.url")"; sha="$(pin "$key.sha256")"
  [ -n "$url" ] && [ -n "$sha" ] || fail "$key: no pinned URL or checksum in pins.json"
  file="$DL/$(basename "$url")"
  if [ ! -f "$file" ] || [ "$(shasum -a 256 "$file" | cut -d' ' -f1)" != "$sha" ]; then
    say "downloading $(basename "$url")"
    curl -fL --retry 3 --silent --show-error "$url" -o "$file.part" || fail "$key: download failed ($url)"
    mv -f "$file.part" "$file"
  fi
  got="$(shasum -a 256 "$file" | cut -d' ' -f1)"
  [ "$got" = "$sha" ] || fail "$key: checksum mismatch (got ${got:0:12}…, pinned ${sha:0:12}…) — not installed"
  echo "$file"
}

mount_dmg() {  # mount_dmg <dmg> <point> — « Y » accepte la licence que certaines images affichent (REAPER)
  mkdir -p "$2"
  printf 'Y\n' | hdiutil attach "$1" -nobrowse -noautoopen -mountpoint "$2" >/dev/null || fail "cannot open $(basename "$1")"
}

unmount_dmg() { hdiutil detach "$1" -quiet >/dev/null 2>&1 || hdiutil detach "$1" -force -quiet >/dev/null 2>&1 || true; }

install_pkg() {  # install_pkg <pkg> <nom>
  installer -pkg "$1" -target / || fail "$2: the package did not install"
}

# ── REAPER : l'image officielle, copiée dans /Applications ──
if [ "$DO_REAPER" = 1 ]; then
  say "REAPER $(pin reaper.version)"
  dmg="$(fetch reaper)" || exit 1
  mnt="$(mktemp -d /tmp/golem-reaper.XXXX)"
  mount_dmg "$dmg" "$mnt"
  app="$(find "$mnt" -maxdepth 1 -name 'REAPER*.app' | head -1)"
  [ -n "$app" ] || { unmount_dmg "$mnt"; fail "REAPER.app not found in the disk image"; }
  rm -rf /Applications/REAPER.app
  ditto "$app" /Applications/REAPER.app || { unmount_dmg "$mnt"; fail "cannot copy REAPER to /Applications"; }
  unmount_dmg "$mnt"
  rmdir "$mnt" 2>/dev/null
  xattr -dr com.apple.quarantine /Applications/REAPER.app 2>/dev/null || true
  ok "REAPER in /Applications"
fi

# ── NAM VST3 : le paquet officiel de l'image (le cœur ampli + baffle) ──
if [ "$DO_NAM" = 1 ]; then
  if [ -d "/Library/Audio/Plug-Ins/VST3/NeuralAmpModeler.vst3" ]; then
    ok "NAM VST3 already installed — kept as is"
  else
    say "Neural Amp Modeler $(pin nam_vst3.version) (VST3)"
    dmg="$(fetch nam_vst3)" || exit 1
    mnt="$(mktemp -d /tmp/golem-nam.XXXX)"
    mount_dmg "$dmg" "$mnt"
    pkg="$(find "$mnt" -maxdepth 2 -name '*.pkg' | head -1)"
    [ -n "$pkg" ] || { unmount_dmg "$mnt"; rmdir "$mnt"; fail "no installer package in the NAM disk image"; }
    installer -pkg "$pkg" -target / || { unmount_dmg "$mnt"; rmdir "$mnt"; fail "NAM: the package did not install"; }
    unmount_dmg "$mnt"
    rmdir "$mnt" 2>/dev/null
    [ -d "/Library/Audio/Plug-Ins/VST3/NeuralAmpModeler.vst3" ] || fail "NAM VST3 missing after its installer"
    ok "NAM VST3 in /Library/Audio/Plug-Ins/VST3"
  fi
  # 0.7.15 bâti par golem (lit les captures A2) par-dessus l'officiel — NON VÉRIFIÉ sur un Mac. Le témoin vit À CÔTÉ du
  # bundle : un fichier ajouté dedans casserait sa signature.
  mark="/Library/Audio/Plug-Ins/VST3/.golem-nam-version"
  if [ "$(cat "$mark" 2>/dev/null)" != "$(pin nam_golem.version)" ]; then
    say "Neural Amp Modeler $(pin nam_golem.version) (golem build — plays A2 captures)"
    z="$(fetch nam_golem)" || exit 1
    tmp="$(mktemp -d /tmp/golem-namg.XXXX)"
    ditto -x -k "$z" "$tmp" || { rm -rf "$tmp"; fail "cannot open the golem NAM archive"; }
    [ -d "$tmp/NeuralAmpModeler.vst3" ] || { rm -rf "$tmp"; fail "no VST3 in the golem NAM archive"; }
    vst="/Library/Audio/Plug-Ins/VST3/NeuralAmpModeler.vst3"
    rm -rf "$vst.golem-prev"
    mv "$vst" "$vst.golem-prev" 2>/dev/null
    # une copie ratée ne laisse PAS « plus de NAM du tout » avec un témoin qui dit OK (audit macOS, 2026-11-04) :
    # l'officiel revient, le témoin n'est pas écrit, le passage suivant réessaie
    if ! ditto "$tmp/NeuralAmpModeler.vst3" "$vst"; then
      rm -rf "$vst"; mv "$vst.golem-prev" "$vst" 2>/dev/null; rm -rf "$tmp"
      fail "cannot install the golem NAM build — the official $(pin nam_vst3.version) is kept"
    fi
    # ditto -x garde le propriétaire de l'archive (l'utilisateur qui l'a bâtie) : dans /Library, root comme le reste
    chown -R root:wheel "$vst"
    xattr -dr com.apple.quarantine "$vst" 2>/dev/null
    codesign --force --deep -s - "$vst" 2>/dev/null
    printf '%s' "$(pin nam_golem.version)" > "$mark"
    rm -rf "$tmp"
    ok "NAM $(pin nam_golem.version) in /Library/Audio/Plug-Ins/VST3"
  fi
fi

# ── AVL Drumkits : le moteur du bloc drumkit (paquet x42 signé, LV2, arm64 + x86_64) ──
if [ "$DO_AVL" = 1 ]; then
  if [ -d "/Library/Audio/Plug-Ins/LV2/avldrums.lv2" ]; then
    ok "AVL Drumkits already installed — kept as is"
  else
    say "AVL Drumkits $(pin avldrums.version) (x42, LV2)"
    pkg="$(fetch avldrums)" || exit 1
    install_pkg "$pkg" "AVL Drumkits"
    [ -d "/Library/Audio/Plug-Ins/LV2/avldrums.lv2" ] || fail "avldrums.lv2 missing after its installer"
    ok "AVL Drumkits in /Library/Audio/Plug-Ins/LV2"
  fi
fi

# ── sfizz : le moteur des kits SFZ (docs/drums-kit.md §6) — paquet sfizz-ui (AU + VST3 + LV2). NON VÉRIFIÉ sur Mac ──
if [ "$DO_SFIZZ" = 1 ]; then
  if [ -d "/Library/Audio/Plug-Ins/LV2/sfizz.lv2" ]; then
    ok "sfizz already installed — kept as is"
  else
    say "sfizz $(pin sfizz.version) (SFZTools, LV2 + VST3 + AU)"
    pkg="$(fetch sfizz)" || exit 1
    install_pkg "$pkg" "sfizz"
    [ -d "/Library/Audio/Plug-Ins/LV2/sfizz.lv2" ] || fail "sfizz.lv2 missing after its installer"
    ok "sfizz in /Library/Audio/Plug-Ins/LV2"
  fi
fi

# ── Vitalium (PawPaw) : le moteur du bloc vital tant que le Vital officiel n'est pas là ──
# Le paquet PawPaw 1.1 (2021, non signé) déclare hostArchitectures=x86_64 alors que ses binaires sont
# universels : sur Apple silicon, `installer` exige Rosetta. On le pose d'abord (licence acceptée en ligne
# de commande — c'est la même que celle de macOS). Un échec de Rosetta est DIT, l'install continue sans
# Vitalium : le bloc vital reste barré et la dernière page propose le Vital officiel.
if [ "$DO_VITALIUM" = 1 ]; then
  if [ -d "/Library/Audio/Plug-Ins/LV2/vitalium.lv2" ]; then
    ok "Vitalium already installed — kept as is"
  else
    say "Vitalium (PawPaw $(pin pawpaw.version), LV2)"
    rosetta=1
    if [ "$(uname -m)" = arm64 ] && ! /usr/bin/arch -x86_64 /usr/bin/true 2>/dev/null; then
      say "Rosetta (the PawPaw package asks for it)"
      softwareupdate --install-rosetta --agree-to-license >/dev/null 2>&1 || rosetta=0
    fi
    if [ "$rosetta" = 0 ]; then
      say "⚠ Rosetta could not be installed — Vitalium skipped; install the official Vital instead (last page)"
    else
      pkg="$(fetch pawpaw)" || exit 1
      install_pkg "$pkg" "PawPaw (Vitalium)"
      [ -d "/Library/Audio/Plug-Ins/LV2/vitalium.lv2" ] || fail "vitalium.lv2 missing after the PawPaw installer"
      ok "Vitalium in /Library/Audio/Plug-Ins/LV2"
    fi
  fi
fi

# ── un paquet dans une image disque : Dragonfly, Proteus ──
install_dmg_pkg() {  # install_dmg_pkg <clé de pins.json> <nom> — l'image se démonte même si le paquet échoue
  local dmg mnt pkg rc=0
  dmg="$(fetch "$1")" || exit 1
  mnt="$(mktemp -d /tmp/golem-$1.XXXX)"
  mount_dmg "$dmg" "$mnt"
  pkg="$(find "$mnt" -maxdepth 2 -name '*.pkg' | head -1)"
  if [ -z "$pkg" ]; then
    rc=1; printf '✗ %s\n' "$2: no installer package in the disk image" >&2
  elif ! installer -pkg "$pkg" -target /; then
    rc=1; printf '✗ %s\n' "$2: the package did not install" >&2
  fi
  unmount_dmg "$mnt"
  rmdir "$mnt" 2>/dev/null
  [ "$rc" = 0 ] || exit 1
}

# ── Dragonfly Reverb : les blocs reverb, reverb-plate, reverb-room (VST3 que effects-macos.json nomme) ──
# 2026-11-04, MacBook Air : la table macOS les nommait, rien ne les posait — la réverbe se taisait sur ~45 presets.
if [ "$DO_DRAGONFLY" = 1 ]; then
  if [ -d "/Library/Audio/Plug-Ins/VST3/DragonflyPlateReverb.vst3" ] && [ -d "/Library/Audio/Plug-Ins/VST3/DragonflyRoomReverb.vst3" ] \
     && [ -d "/Library/Audio/Plug-Ins/VST3/DragonflyHallReverb.vst3" ]; then
    ok "Dragonfly Reverb already installed — kept as is"
  else
    say "Dragonfly Reverb $(pin dragonfly.version) (Hall, Plate, Room — VST3)"
    install_dmg_pkg dragonfly "Dragonfly Reverb"
    for b in DragonflyHallReverb DragonflyPlateReverb DragonflyRoomReverb; do
      [ -d "/Library/Audio/Plug-Ins/VST3/$b.vst3" ] || fail "$b.vst3 missing after the Dragonfly installer"
    done
    ok "Dragonfly Reverb in /Library/Audio/Plug-Ins/VST3"
  fi
fi

# ── Proteus (GuitarML) : le bloc boost ──
if [ "$DO_PROTEUS" = 1 ]; then
  if [ -d "/Library/Audio/Plug-Ins/VST3/Proteus.vst3" ]; then
    ok "Proteus already installed — kept as is"
  else
    say "Proteus $(pin proteus.version) (the Boost block — VST3)"
    install_dmg_pkg proteus "Proteus"
    [ -d "/Library/Audio/Plug-Ins/VST3/Proteus.vst3" ] || fail "Proteus.vst3 missing after its installer"
    ok "Proteus in /Library/Audio/Plug-Ins/VST3"
  fi
fi

ok "system step done"
exit 0
