#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Plugins neuraux non packagés (releases GitHub) → ~/.lv2
# Le cœur de GoleM. Versions épinglées (reproductibilité) ; bump volontaire.
# Vérifier les versions : https://github.com/<repo>/releases/latest
set -euo pipefail
LV2="${HOME}/.lv2"; VST3="${HOME}/.vst3"
mkdir -p "$LV2" "$VST3"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-fetch.sh"      # fetch_verified : empreintes épinglées
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"    # reçu d'install : ce qu'on pose dans ~/.lv2

# Télécharge $1, extrait, copie tout *.lv2 trouvé dans ~/.lv2
install_lv2() {
  local name="$1"
  local url="$2"
  local d="$tmp/$name"
  echo "  ↓ $name"
  mkdir -p "$d"
  if ! fetch_verified "$url" "$d/archive"; then return 0; fi
  case "$url" in
    *.tgz|*.tar.gz) tar -xzf "$d/archive" -C "$d" ;;
    *.tar.xz)       tar -xJf "$d/archive" -C "$d" ;;
    *.zip)          unzip -oq "$d/archive" -d "$d" ;;
  esac
  local found=0
  while IFS= read -r -d '' lv2dir; do
    local ex; ex=$(receipt_existed "$LV2/$(basename "$lv2dir")")   # déjà là avant nous ? (le reçu le garde)
    cp -r "$lv2dir" "$LV2/"; echo "    ✓ $(basename "$lv2dir") → $LV2"; found=1
    # shellcheck disable=SC2086
    receipt_add "$LV2/$(basename "$lv2dir")" dir plugins $ex
  done < <(find "$d" -maxdepth 4 -name '*.lv2' -type d -print0)
  [ "$found" = 1 ] || echo "    ⚠ aucun .lv2 trouvé dans l'archive ($name)"
}

# --- NAM — neural-amp-modeler-lv2 (mikeoliphant) ----------------------------
NAM_VER="v0.2.2"
# build x64v3 (le 8500G est un Zen 4) — support NAM A2 via NeuralAudio interne
# ⚠ La release fait tomber Reaper sur des changements de patch rapprochés : provision/install-nam.sh la recompile avec
# notre correctif et la REMPLACE (docs/audit-2026-10-14-crash-nam.md). On ne réécrase donc jamais une version corrigée :
# la release ne sert que de base sur une machine neuve, avant que install.sh passe install-nam.sh.
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-prebuilt.sh"   # cpu_x86_64_v3
if grep -q "retired model(s) freed by the worker" "$LV2/neural_amp_modeler.lv2/neural_amp_modeler.so" 2>/dev/null; then
  echo "  = NAM corrigé déjà en place (install-nam.sh) — release non reposée"
elif ! cpu_x86_64_v3; then
  # la release est x64v3 : sur un processeur sans AVX2/FMA, REAPER meurt en « invalid opcode » au premier ampli
  # (2026-11-03, i5-3337U). install-nam.sh la compile pour cette machine ; tant qu'il n'a pas réussi, pas de NAM.
  echo "  ⚠ NAM : processeur sans AVX2/FMA — release x64v3 NON posée (install-nam.sh compile pour cette machine)"
else
  install_lv2 "NAM" \
    "https://github.com/mikeoliphant/neural-amp-modeler-lv2/releases/download/${NAM_VER}/neural_amp_modeler_lv2_linux_x64v3.tgz"
fi

# --- AIDA-X (AidaDSP) -------------------------------------------------------
AIDA_VER="1.1.0"
install_lv2 "AIDA-X" \
  "https://github.com/AidaDSP/AIDA-X/releases/download/${AIDA_VER}/AIDA-X-${AIDA_VER}-linux-x86_64.tar.xz"

# --- Ratatouille.lv2 (brummer10) — le cœur (2 NAM + 2 IR) -------------------
RATA_VER="v0.9.11"
install_lv2 "Ratatouille" \
  "https://github.com/brummer10/Ratatouille.lv2/releases/download/${RATA_VER}/Ratatouille.lv2-${RATA_VER}-linux-x86_64.tar.xz"

# --- Aether (Dougal-s) — reverb algorithmique moderne, luxuriante ----------
AETHER_VER="v1.2.1"
install_lv2 "Aether" \
  "https://github.com/Dougal-s/Aether/releases/download/${AETHER_VER}/Aether-${AETHER_VER}-Linux.tar.xz"

# --- À scripter au prochain bump (VST3, pas de .lv2 simple) -----------------
echo "  ℹ ChowDSP (Chow Centaur/Tape/Phaser) : VST3 depuis chowdsp.com → $VST3"
echo "  ℹ Airwindows (Airwin2rack) : VST3/CLAP/LV2 depuis github baconpaul/airwin2rack"
echo "  ℹ GuitarML (TS-M1N3, Proteus) : VST3 depuis guitarml.com → $VST3"
echo "  ℹ GxPlugins/OD : couverts par 'guitarix' (apt) ou releases brummer10"

echo
echo "  LV2 installés dans : $LV2"
ls -1 "$LV2" 2>/dev/null | sed 's/^/    /'
echo "  → Dans Reaper : Preferences/Plug-ins/LV2 → re-scan."

# --- Dexed — EP FM DX7 (bloc ep, lane Keys — P1 claviers) --------------------
# VST3 JUCE (chargement banque+patch par vst_chunk, technique Vital)
DEXED_VER="1.0.1"
d="$tmp/dexed"; mkdir -p "$d"
echo "  ↓ Dexed $DEXED_VER"
if fetch_verified "https://github.com/asb2m10/dexed/releases/download/v${DEXED_VER}/Dexed-${DEXED_VER}-lnx.zip" "$d/dexed.zip"; then
  ex=$(receipt_existed "$VST3/Dexed.vst3")
  # shellcheck disable=SC2086
  unzip -oq "$d/dexed.zip" -d "$d" && cp -r "$d/Dexed.vst3" "$VST3/" && echo "    ✓ Dexed.vst3 → $VST3" \
    && receipt_add "$VST3/Dexed.vst3" dir plugins $ex
else echo "    ✗ download échec Dexed"; fi
