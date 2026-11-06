#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Installe TOUS les plugins audio du rig GoleM (Ubuntu 24.04 / Noble).
# Les blocs de effects.json (docs/archive/algo-pedals-oss.md, docs/archive/named-pedals.md) résolvent
# leur plugin par nom côté golem_rig ; ce script garantit qu'ils sont présents.
#   sudo ./provision/install-plugins.sh
# Après l'install : Reaper ne scanne les nouveaux LV2 qu'au DÉMARRAGE -> redémarrer
# Reaper (ou Prefs > Plug-ins > Re-scan) pour que les blocs chargent.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive   # aucun paquet ne pose de question : l'installateur n'a pas de terminal

# Ce script tourne en `sudo` : $HOME est celui de ROOT. Les plugins utilisateur (~/.vst3,
# ~/.lv2) doivent aller chez l'appelant, sinon ils atterrissent dans /root et Reaper ne les
# voit jamais — panne silencieuse et déroutante.
USER_HOME=$(getent passwd "${SUDO_USER:-$USER}" | cut -d: -f6)
USER_HOME="${USER_HOME:-$HOME}"
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-fetch.sh"      # fetch_verified : empreintes épinglées
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/lib-receipt.sh"    # reçu d'install (sous sudo : celui de $SUDO_USER)

echo "== 1. Plugins LV2 par apt (universe) =="
# calf-plugins        : chorus/flanger/phaser/tremolo/rotary (Calf *)
# x42-plugins         : dpl (limiter), IR Convolver (cab), x42-eq
# dragonfly-reverb-lv2: reverb hall/plate/room/early
# guitarix-lv2        : gx_* (wah, octaver gx_oc_2, vibrato, detune, muff, scream, echocat, shimmer…)
# zam-plugins         : Zam* (ZamGrains = granular freeze, ZamGEQ31, ZaMaximX2…)
# mda-lv2             : mda (RingMod, Degrade=bitcrusher, RezFilter, SubSynth, TalkBox…)
# byod                : BYOD (distorsion modulaire)
# avldrums.lv2 (+soundfont) : moteur de batterie « avldrums » (blocs drums)
# drumgizmo           : moteur de batterie multi-micro (kit Aasimonster, cf. fetch-assets.sh)
#   ⚠ ces deux-là étaient ABSENTS d'ici : présents sur le poste de dev par une install
#   manuelle oubliée, donc invisibles — une VM nue a montré qu'un rack neuf perdait deux
#   des trois moteurs de batterie (2026-08-02).
apt-get -o DPkg::Lock::Timeout=300 update -qq || echo "  ⚠ un dépôt a échoué — on continue avec l'index disponible"
# une seule liste : celle qu'on demande à apt est celle que le reçu note comme explicite (apt.requested)
APT_PKGS=(calf-plugins x42-plugins dragonfly-reverb-lv2 guitarix-lv2 zam-plugins mda-lv2 byod
          avldrums.lv2 avldrums.lv2-soundfont drumgizmo)
receipt apt-snapshot before
receipt apt-requested "${APT_PKGS[@]}"
apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -y "${APT_PKGS[@]}"
receipt apt-snapshot after

echo "== 2. Surge XT (FX : ring mod, spring reverb, résonant, Nimbus, Treemonster) =="
# Pas packagé Ubuntu 24.04 -> .deb officiel (Surge Synth Team). Fournit le LV2 « Surge XT Effects » (un plugin,
# sélecteur de type interne). RELEASE épinglée (audit 2026-10-15) : c'était la Nightly — un binaire différent chaque
# nuit, impossible à vérifier.
SURGE_VER="1.3.4"
SURGE_DEB="$(mktemp -d)/surge-xt-$SURGE_VER.deb"
if ! ls "/usr/lib/lv2/" 2>/dev/null | grep -qi "Surge XT Effects"; then
  URL="https://github.com/surge-synthesizer/releases-xt/releases/download/$SURGE_VER/surge-xt-linux-x64-$SURGE_VER.deb"
  echo "→ download $URL"
  if fetch_verified "$URL" "$SURGE_DEB"; then
    # reçu : le NOM du paquet est lu dans le .deb, jamais deviné ; à nous seulement s'il n'était pas installé
    pkg="$(dpkg-deb -f "$SURGE_DEB" Package 2>/dev/null || true)"
    was="$(dpkg-query -W -f='${db:Status-Status}' "$pkg" 2>/dev/null || true)"
    receipt apt-snapshot before
    if [ -n "$pkg" ]; then receipt apt-requested "$pkg"; fi
    dpkg -i "$SURGE_DEB" || apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -f -y
    if [ -n "$pkg" ] && [ "$was" != installed ]; then receipt deb "$pkg"; fi
    receipt apt-snapshot after
    rm -f "$SURGE_DEB"
  else
    echo "✗ Surge XT non installé"
  fi
else
  echo "✓ Surge XT Effects déjà présent"
fi

echo "== 3. SWS (extension Reaper — sentinelle MIDI golem_midi : réparation À CHAUD des masques) =="
# Version ÉPINGLÉE (doctrine releases, jamais latest). SWS donne SNM_Set/GetIntConfigVar :
# sans lui, golem_midi.lua ne peut que DÉTECTER une dérive des devices MIDI (valse USB) ;
# avec lui, il la répare en ~5 s sans redémarrer Reaper. Install utilisateur (pas de root).
SWS_VER="v2.14.0.7"
SWS_SO="$USER_HOME/.config/REAPER/UserPlugins/reaper_sws-x86_64.so"   # pas $HOME : sous sudo, c'est celui de root
if [ ! -f "$SWS_SO" ]; then
  # ⚠ AU NOM DE L'UTILISATEUR, jamais en root (VM vierge, 2026-10-15) : sur une machine neuve ~/.config n'existe pas
  # encore, et un `mkdir -p` en root créait ~/.config, ~/.config/REAPER et UserPlugins À ROOT — setup-reaper.sh (en
  # utilisateur) ne pouvait plus rien y poser, l'install mourait là, et ~/.config à root casse aussi les autres logiciels.
  SWS_USER="${SUDO_USER:-$USER}"
  sudo -u "$SWS_USER" -H mkdir -p "$(dirname "$SWS_SO")"
  echo "→ download SWS $SWS_VER"
  SWS_TMP="$(mktemp)"
  if fetch_verified "https://github.com/reaper-oss/sws/releases/download/$SWS_VER/reaper_sws-x86_64.so" "$SWS_TMP" \
     && install -o "$SWS_USER" -g "$(id -gn "$SWS_USER")" -m 755 "$SWS_TMP" "$SWS_SO"; then
    echo "✓ SWS installé ($SWS_SO)"
    receipt_add "$SWS_SO" file plugins
  else
    echo "✗ download SWS échoué — golem_midi restera en mode détection seule"
  fi
  rm -f "$SWS_TMP"
else
  echo "✓ SWS déjà présent"
fi

echo "== 4. Vitalium / Vital (lane Keys — bloc vital) =="
# ⚠ NON AUTOMATISABLE, et c'est vérifié plutôt que supposé (2026-08-02) : Vitalium n'est
# packagé NI dans Ubuntu 24.04, NI chez KXStudio, et la dernière release DISTRHO-Ports
# (2021-03-15) ne publie aucun binaire. Le Vital officiel, lui, demande un compte vital.audio.
# On ne peut donc que CONSTATER — mais on le dit fort, parce que sans lui la lane Keys est
# entièrement MUETTE et que ça ne se découvre sinon qu'en jouant.
# golem_rig accepte l'un ou l'autre : VST3i:Vital, puis VST3i:Vitalium, puis Vitalium.
if [ -d "$USER_HOME/.vst3/Vital.vst3" ] || [ -d "$USER_HOME/.vst3/vitalium.vst3" ] \
   || [ -d "$USER_HOME/.lv2/vitalium.lv2" ]; then
  echo "✓ Vital ou Vitalium présent — lane Keys opérationnelle"
else
  echo "✗ NI Vital NI Vitalium — LA LANE KEYS SERA MUETTE."
  echo "   Vital     : https://vital.audio (compte gratuit, .deb officiel)"
  echo "   Vitalium  : build libre depuis DISTRHO-Ports (pas de binaire publié)"
  echo "   → déposer dans ~/.vst3/ (et/ou ~/.lv2/), puis redémarrer Reaper."
fi

echo "== 5. MANUELS (non automatisés ici — voir docs) =="
# NAM (blocs amp/amp-nam/pedal-nam) : neural_amp_modeler LV2 dans ~/.lv2/
#   -> github.com/mikeoliphant/neural-amp-modeler-lv2 (release Linux)
# Vital / Vitalium (lane Keys, bloc vital) : ~/.vst3 + ~/.lv2/
#   -> Vital = download proprio (vital.audio) ; Vitalium = build libre
# sfizz (bloc piano) : provision/install-sfizz.sh
echo "   NAM        -> ~/.lv2/neural_amp_modeler.lv2 (github mikeoliphant, manuel)"
echo "   Vital/Vitalium -> voir l'étape 4 ci-dessus (aucun paquet ne l'installe)"
echo "   sfizz      -> ./provision/install-sfizz.sh"
echo "   Prisma (Grit) -> ./provision/install-prisma.sh (build depuis la source)"
echo "   Spectral Comp / Stretch -> ./provision/install-spectral.sh (build depuis la source, docs/spectral.md)"

echo
echo "✓ Plugins apt + Surge installés. REDÉMARRER Reaper pour le rescan LV2."
