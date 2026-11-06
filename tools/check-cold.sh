#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# La batterie À FROID : tout ce qui se vérifie SANS bridge, sans Reaper, sans matériel.
# Né de l'audit 2026-08-12 : les checks existaient, mais aucun point d'entrée unique ne les
# lançait — une suite qui ne tourne que si quelqu'un y pense ne protège personne.
#
#   ./tools/check-cold.sh          # tout, s'arrête à la fin, RC != 0 si un étage échoue
#
# L'étage JS de check-meter demande le bridge : il vit dans la batterie RIG (check-meter --rig),
# pas ici — d'où le --skip-js EXPLICITE (sans lui, check-meter échoue fort, et c'est voulu).
set -u
cd "$(dirname "$0")/.."
fail=0
run() { echo; echo "══════ $* ══════"; "$@" || fail=1; }

run python3 -m pytest tests/ -q
run ./tools/check-descriptors.py
run ./tools/fcb/check-uno2.py
run ./tools/check-transcribe.py
run ./tools/check-standards.py
run ./tools/check-meter.py --skip-js

echo
if [ "$fail" = 0 ]; then
  echo "CHECK-COLD : tout est vert"
else
  echo "CHECK-COLD : ÉCHEC(S) — voir ci-dessus"
fi
exit "$fail"
