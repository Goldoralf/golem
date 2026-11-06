# shellcheck shell=bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Les plugins PRÉCOMPILÉS (Goldoralf/golem-binaries) pour install-zconvo/nam/prisma/spectral.sh : on essaie le binaire
# épinglé d'abord, on compile les mêmes commits seulement s'il manque (2026-10-23 : ~10 min de moins par install).
# À sourcer APRÈS avoir posé USER_NAME et lib-receipt.sh.
#   prebuilt <asset> <dossier> <bundle>     0 = posé (chez l'utilisateur), 1 = à compiler
#   runtime_libs <paquet>…                  les bibliothèques que le binaire charge, SANS les -dev de la compilation
#   compiling <secondes>                    dit à l'installateur graphique que la phase s'allonge (compilation mesurée)
LIB_PREBUILT_HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# LE PROCESSEUR SAIT-IL x86-64-v3 ? (2026-11-03) Les précompilés de golem-binaries visent -march=x86-64-v3 (AVX2, FMA,
# BMI2…). Un portable Ivy Bridge (i5-3337U, 2013 : AVX sans AVX2) chargeait le NAM précompilé et REAPER mourait au
# premier rappel — « trap invalid opcode … in neural_amp_modeler.so », sans une ligne dans son journal.
# 0 = oui (ou pas un x86 : la question ne se pose pas), 1 = non → compiler ici, pour CE processeur.
cpu_x86_64_v3() {
  [ "$(uname -m)" = x86_64 ] || return 0
  local f
  for f in avx2 fma bmi2; do grep -qw "$f" /proc/cpuinfo || return 1; done
  return 0
}

prebuilt() {
  if [ "$(id -un)" = "$USER_NAME" ]; then
    "$LIB_PREBUILT_HERE/fetch-prebuilt.sh" "$@"
  else
    sudo -u "$USER_NAME" -H env GOLEM_BUILD_FROM_SOURCE="${GOLEM_BUILD_FROM_SOURCE:-0}" \
      "$LIB_PREBUILT_HERE/fetch-prebuilt.sh" "$@"
  fi
}

# NEEDED des binaires de linux-plugins-v1 et v2 (readelf -d), ramenés à leurs paquets Ubuntu 24.04 : une machine qui n'a
# jamais compilé n'a pas les -dev qui les tiraient. Déjà là le plus souvent — apt ne fait alors rien.
runtime_libs() {
  [ "$(id -u)" = 0 ] || return 0
  receipt apt-snapshot before
  receipt apt-requested "$@"
  DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold \
    install -y -qq "$@" >/dev/null
  receipt apt-snapshot after
}

# L'installateur graphique (installer/phases.py) annonce la phase « Building » avec les binaires précompilés (~30 s) ;
# quand il faut compiler, chaque script ajoute SA durée mesurée (VM Ubuntu 24.04, 6 cœurs, 2026-10-23) — sinon
# l'écran dirait « 10 s » pendant dix minutes. Muet hors de l'installateur.
compiling() {
  if [ "${GOLEM_INSTALLER:-}" = 1 ]; then echo "@@est-add $1"; fi
}
