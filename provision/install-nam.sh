#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# L'AMPLI NAM (mikeoliphant neural-amp-modeler-lv2 — les blocs amp / pedal / preamp / comp NAM), compilé DEPUIS LA
# SOURCE avec notre correctif, et posé dans ~/.lv2 À LA PLACE du binaire de la release (provision/plugins.sh).
#
#   sudo ./provision/install-nam.sh      (sudo seulement si cmake / g++ / git manquent ; sinon sans)
#
# Pourquoi (docs/audit-2026-10-14-crash-nam.md) : la release v0.2.2 faisait tomber Reaper sur des changements de
# patch rapprochés — mesuré le 2026-10-14 : crash vers 50 rappels à 0,5-0,8 s, trois signatures (GPF dans
# NeuralAudio::Process, « double free or corruption », GPF dans la file de travaux LV2 de Reaper). Le plugin dépose
# des travaux (schedule_work) depuis le fil PRINCIPAL — restore() avec le planificateur de l'instance, et
# work_response() que Reaper appelle sur ce fil quand il retire une instance — pendant que les fils audio utilisent la
# même file. Le correctif (provision/patches/nam-thread-safe-worker.patch) : restore() prend le planificateur que
# l'hôte lui passe, et work_response() ne dépose plus rien (l'ancien modèle part dans un casier que le worker vide).
# Avec lui : 180 rappels sans crash.
#
# Ce script tourne en `sudo` ou non : la compilation et le plugin (~/.lv2) se font chez l'APPELANT ($SUDO_USER).
# Puis : REDÉMARRER Reaper (POST /api/system/reaper-restart) — il ne charge ses plugins qu'au démarrage.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive   # aucun paquet ne pose de question : l'installateur n'a pas de terminal

HERE="$(cd "$(dirname "$0")" && pwd)"
NAM_REPO="https://github.com/mikeoliphant/neural-amp-modeler-lv2.git"
NAM_COMMIT="35c28a52ec0a89af16208e953544dc96e13dde20"     # tag v0.2.2 (= la release posée par plugins.sh)
NAM_PATCH="$HERE/patches/nam-thread-safe-worker.patch"
# la chaîne que SEUL le binaire corrigé contient : c'est elle qu'on relit
NAM_MARK="retired model(s) freed by the worker"
USER_NAME="${SUDO_USER:-${USER:-$(id -un)}}"
USER_HOME=$(getent passwd "$USER_NAME" | cut -d: -f6)
USER_HOME="${USER_HOME:-$HOME}"
BUILD_ROOT="$USER_HOME/.cache/golem-build"
SRC="$BUILD_ROOT/neural-amp-modeler-lv2"
DEST="$USER_HOME/.lv2/neural_amp_modeler.lv2"
. "$HERE/lib-receipt.sh"      # reçu d'install (sous sudo : celui de $SUDO_USER)

run_as_user() {
  if [ "$(id -un)" = "$USER_NAME" ]; then bash -c "$1"; else sudo -u "$USER_NAME" -H bash -c "$1"; fi
}

. "$HERE/lib-prebuilt.sh"
# COMPILÉ ICI : la marque posée dans le bundle par une compilation sur CETTE machine (-DUSE_NATIVE_ARCH). Sur un
# processeur sans x86-64-v3, le binaire précompilé — ou la release de plugins.sh — y meurt en « invalid opcode » : seul
# un NAM compilé ici est bon, et un NAM déjà posé sans cette marque est remplacé.
BUILT_HERE="$DEST/.golem-built-here"
if cpu_x86_64_v3; then V3=1; else V3=0; echo "→ processeur sans AVX2/FMA (x86-64-v3) : NAM compilé pour cette machine"; fi
# UN ÉCHEC NE LAISSE PAS DE NAM QUI TUE REAPER (2026-11-03). Sans x86-64-v3, si la compilation n'aboutit pas (outils
# absents, sous-modules introuvables, mémoire…), le NAM en place — la release de plugins.sh — fait mourir REAPER au
# premier patch qui contient un ampli. On le RETIRE : REAPER démarre, les blocs NAM manquent (dit comme un plugin
# absent), le reste du rig joue. Relancer ce script une fois la cause réglée le repose.
nam_unsafe_cleanup() {
  local rc=$?
  if [ "$rc" != 0 ] && [ "$V3" = 0 ] && [ -e "$DEST" ] && [ ! -f "$BUILT_HERE" ]; then
    run_as_user "rm -rf '$DEST'" || rm -rf "$DEST"
    echo "✗ NAM non compilé pour ce processeur (sans AVX2/FMA) : NAM retiré pour que REAPER démarre — les blocs ampli NAM" \
         "sont indisponibles. Relancer : sudo ./provision/install-nam.sh" >&2
  fi
}
trap nam_unsafe_cleanup EXIT
trap 'exit 130' INT; trap 'exit 143' TERM   # interrompu (Ctrl-C, kill) : bash ne passerait pas par EXIT sans ça
# PRÉCOMPILÉ d'abord (Goldoralf/golem-binaries) : même commit, même correctif, -march=x86-64-v3 — marque vérifiée
ex=$(receipt_existed "$DEST")     # la release de plugins.sh, ou un NAM d'avant golem : le reçu le sait déjà
if [ "$V3" = 1 ] && prebuilt neural_amp_modeler.lv2 "$USER_HOME/.lv2" neural_amp_modeler.lv2; then
  # sans la marque du correctif, ce n'est pas notre binaire : on le retire et on compile
  grep -q "$NAM_MARK" "$DEST/neural_amp_modeler.so" || { rm -rf "$DEST"; echo "✗ précompilé sans le correctif — compilation" >&2; }
fi
if [ -f "$DEST/neural_amp_modeler.so" ] && grep -q "$NAM_MARK" "$DEST/neural_amp_modeler.so" && [ "${GOLEM_BUILD_FROM_SOURCE:-0}" != 1 ] \
    && { [ "$V3" = 1 ] || [ -f "$BUILT_HERE" ]; }; then
  receipt_add "$DEST" dir plugins $ex
  if [ "$V3" = 1 ]; then echo "✓ NAM corrigé posé : $DEST (GPL-3.0, précompilé)"; else echo "✓ NAM corrigé déjà compilé pour ce processeur : $DEST (GPL-3.0)"; fi
  exit 0
fi

compiling 145
echo "== 1. Outils de compilation =="
if command -v cmake >/dev/null && command -v g++ >/dev/null && command -v git >/dev/null; then
  echo "   déjà présents"
elif [ "$(id -u)" = 0 ]; then
  receipt apt-snapshot before
  APT_PKGS=(build-essential cmake git)
  receipt apt-requested "${APT_PKGS[@]}"
  apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -y "${APT_PKGS[@]}"
  receipt apt-snapshot after
else
  echo "✗ cmake / g++ / git manquent — relancer avec sudo" >&2
  exit 1
fi

echo "== 2. Source épinglée + correctif =="
run_as_user "mkdir -p '$BUILD_ROOT'"
receipt_add "$BUILD_ROOT" dir golem
if [ ! -d "$SRC/.git" ]; then
  run_as_user "git clone -q '$NAM_REPO' '$SRC'"
fi
# on repart TOUJOURS de la source propre : un patch déjà appliqué ne s'applique pas deux fois
run_as_user "cd '$SRC' && git fetch -q origin && git checkout -q -f '$NAM_COMMIT' && git clean -qfdx"
# les sous-modules viennent en partie de gitlab.com (Eigen), qui refuse « due to load » par moments : 2 installs VM
# sur 3 sont mortes là le 2026-10-23. On réessaie en espaçant — git vérifie le commit épinglé de chaque sous-module,
# un nouvel essai ne peut rien amener d'autre.
ok=0
for wait_s in 0 20 60 120; do
  [ "$wait_s" -gt 0 ] && { echo "  ↻ sous-modules indisponibles — nouvel essai dans ${wait_s} s"; sleep "$wait_s"; }
  if run_as_user "cd '$SRC' && git submodule update -q --init --recursive"; then ok=1; break; fi
done
[ "$ok" = 1 ] || { echo "✗ sous-modules introuvables après 4 essais (gitlab.com surchargé ?)" >&2; exit 1; }
run_as_user "cd '$SRC' && git apply --check '$NAM_PATCH' && git apply '$NAM_PATCH'"

# USE_NATIVE_ARCH=ON ne veut PAS dire « natif » : src/CMakeLists.txt de NAM pose alors -march=x86-64-v3 (lu au commit
# épinglé, 2026-11-03). Sans x86-64-v3 : l'option coupée, et -march=native — l'AVX qu'a la machine, rien de plus.
if [ "$V3" = 1 ]; then ARCH_OPTS="-DUSE_NATIVE_ARCH=ON"; ARCH_TXT="x86-64-v3 comme la release officielle"
else ARCH_OPTS="-DUSE_NATIVE_ARCH=OFF -DCMAKE_C_FLAGS=-march=native -DCMAKE_CXX_FLAGS=-march=native"; ARCH_TXT="-march=native : ce processeur"; fi
echo "== 3. Compilation (Release, $ARCH_TXT) =="
run_as_user "cd '$SRC' && cmake -S . -B build -DCMAKE_BUILD_TYPE=Release $ARCH_OPTS >/dev/null \
  && cmake --build build -j$(nproc) >/dev/null"
BUILT="$SRC/build/neural_amp_modeler.lv2"
if ! grep -q "$NAM_MARK" "$BUILT/neural_amp_modeler.so"; then
  echo "✗ le binaire compilé ne contient pas le correctif — rien n'est installé" >&2
  exit 1
fi

echo "== 4. Pose dans ~/.lv2 (remplace le binaire de la release) =="
ex=$(receipt_existed "$DEST")     # la release de plugins.sh, ou un NAM d'avant golem : le reçu le sait déjà
run_as_user "mkdir -p '$USER_HOME/.lv2' && rm -rf '$DEST' && cp -r '$BUILT' '$DEST' && touch '$BUILT_HERE'"
grep -q "$NAM_MARK" "$DEST/neural_amp_modeler.so"
# shellcheck disable=SC2086
receipt_add "$DEST" dir plugins $ex
echo "✓ NAM corrigé posé : $DEST (GPL-3.0)"
echo "  → redémarrer Reaper, puis vérifier lequel il a chargé :"
echo "    grep -o '/[^ ]*neural_amp_modeler.so' /proc/\$(pgrep -x reaper)/maps | sort -u"
