#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Le CONVOLVEUR D'IR (x42 zeroconvo.lv2 — le bloc `cab`), au commit amont qui corrige le crash, posé dans ~/.lv2 où il
# PASSE DEVANT celui du paquet `x42-plugins`.
#
#   sudo ./provision/install-zconvo.sh
#
# Pourquoi on ne garde pas celui d'apt (docs/audit-2026-10-01-crash-convolveur.md) :
#   - il tuait Reaper ~1 fois sur 10 sur des changements de preset rapprochés : son worker détruit
#     le moteur de convolution qu'il vient de charger quand deux restaurations d'état se suivent sur
#     une instance neuve. Corrigé EN AMONT le 2026-10-02 (05405cb, x42/zconvo.lv2#12, après notre signalement) :
#     notre patch (zconvo-retired-engines.patch) est retiré le 2026-11-03, le reproducteur
#     provision/patches/zconvo-repro/ passe sur 05405cb (ASan, 300 passes) et casse sur v0.7.2 ;
#   - le paquet Ubuntu 24.04 (0.7.1) est compilé AVEC ses assertions (un `assert` qui échoue dans le
#     thread audio = abort de Reaper) et sans deux correctifs amont de 2025 (redémarrage rapide qui
#     corrompt la mémoire ; arrêt du moteur après cinq cycles en retard).
#
# Ce script tourne en `sudo` : les en-têtes vont dans le système ; la compilation et le plugin
# (~/.lv2) chez l'APPELANT ($SUDO_USER), sinon Reaper ne le verrait jamais. Si les en-têtes sont
# déjà là, il tourne aussi SANS sudo.
# Puis : REDÉMARRER Reaper (POST /api/system/reaper-restart) — il ne charge ses plugins qu'au démarrage.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive   # aucun paquet ne pose de question : l'installateur n'a pas de terminal

HERE="$(cd "$(dirname "$0")" && pwd)"
ZC_REPO="https://github.com/x42/zconvo.lv2.git"
ZC_COMMIT="05405cb508ec19ab725081e12dbf9979c6e95ae5"       # v0.7.2 + « Work around double restore » (2026-10-02)
# le correctif amont ne laisse aucune chaîne dans le binaire : le bundle porte le commit dont il est fait
# (golem-build.txt, écrit ici et par golem-binaries build.sh) — c'est lui qu'on relit
ZC_STAMP="x42/zconvo.lv2 $ZC_COMMIT"
ours() { [ -f "$DEST/zeroconvolv.so" ] && [ "$(cat "$DEST/golem-build.txt" 2>/dev/null)" = "$ZC_STAMP" ]; }
USER_NAME="${SUDO_USER:-${USER:-$(id -un)}}"
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
USER_HOME="${USER_HOME:-$HOME}"
BUILD_ROOT="$USER_HOME/.cache/golem-build"
ZC_DIR="$BUILD_ROOT/zconvo.lv2"
DEST="$USER_HOME/.lv2/zeroconvo.lv2"
. "$HERE/lib-receipt.sh"      # reçu d'install (sous sudo : celui de $SUDO_USER)

run_as_user() {
  if [ "$(id -un)" = "$USER_NAME" ]; then bash -c "$1"; else sudo -u "$USER_NAME" -H bash -c "$1"; fi
}

. "$HERE/lib-prebuilt.sh"
# PRÉCOMPILÉ d'abord (Goldoralf/golem-binaries) : même commit, même correctif — sa marque est vérifiée comme ici
ex=$(receipt_existed "$DEST")
if prebuilt zeroconvo.lv2 "$USER_HOME/.lv2" zeroconvo.lv2; then
  # pas fait du bon commit : ce n'est pas notre binaire, on le retire et on compile
  ours || { rm -rf "$DEST"; echo "✗ précompilé d'un autre commit — compilation" >&2; }
fi
if ours && [ "${GOLEM_BUILD_FROM_SOURCE:-0}" != 1 ]; then
  runtime_libs libsndfile1 libsamplerate0 libfftw3-single3
  receipt_add "$DEST" dir plugins $ex
  echo "✓ convolveur d'IR corrigé posé : $DEST (GPL-2.0-or-later, précompilé)"
  exit 0
fi

compiling 15
echo "== 1. En-têtes (apt) =="
if pkg-config --exists lv2 sndfile samplerate fftw3f 2>/dev/null && command -v g++ >/dev/null && command -v git >/dev/null; then
  echo "   déjà présents"
else
  receipt apt-snapshot before
  APT_PKGS=(build-essential git pkg-config lv2-dev libsndfile1-dev libsamplerate0-dev libfftw3-dev)
  receipt apt-requested "${APT_PKGS[@]}"
  apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -y "${APT_PKGS[@]}"
  receipt apt-snapshot after
fi

echo "== 2. Source épinglée =="
run_as_user "mkdir -p '$BUILD_ROOT'"
receipt_add "$BUILD_ROOT" dir golem
if [ ! -d "$ZC_DIR/.git" ]; then
  run_as_user "git clone -q '$ZC_REPO' '$ZC_DIR'"
fi
# on repart TOUJOURS de la source propre (un ancien build y gardait notre patch appliqué)
run_as_user "cd '$ZC_DIR' && git fetch -q origin && git checkout -q -f '$ZC_COMMIT' && git clean -qfdx"

echo "== 3. Compilation (options amont : -O3 -DNDEBUG, pas d'assertion dans le thread audio) =="
run_as_user "cd '$ZC_DIR' && make -j$(nproc) >/dev/null"

echo "== 4. Pose dans ~/.lv2 (passe devant /usr/lib/lv2) =="
ex=$(receipt_existed "$DEST")
run_as_user "mkdir -p '$USER_HOME/.lv2' && rm -rf '$DEST' && cd '$ZC_DIR' && make install LV2DIR='$USER_HOME/.lv2' >/dev/null"
run_as_user "echo '$ZC_STAMP' > '$DEST/golem-build.txt'"
ours
# shellcheck disable=SC2086
receipt_add "$DEST" dir plugins $ex
echo "✓ convolveur d'IR corrigé posé : $DEST (GPL-2.0-or-later)"
echo "  → redémarrer Reaper, puis vérifier lequel il a chargé :"
echo "    grep -o '/[^ ]*zeroconvolv.so' /proc/\$(pgrep -x reaper)/maps | sort -u"
echo "    ./tools/check-recall-stress.sh 40     # attendu : 0 crash"
