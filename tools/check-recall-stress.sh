#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Reaper TIENT-IL des changements de preset rapprochés ? — compté, passe par passe.
#
#   ./tools/check-recall-stress.sh        # 12 passes
#   ./tools/check-recall-stress.sh 30     # 30 passes
#
# POURQUOI : le 2026-10-01, en validant le portage Windows, Reaper est tombé quatorze fois dans
# l'après-midi sur cette séquence — trois rebuilds de preset en moins de trois secondes, ce que fait
# check-foot.py (PC 0, PC 1, puis retour à l'état d'origine) : 12 crashs sur 85 passes, code d'avant
# le portage compris. La cause n'était pas chez nous : le convolveur d'IR x42 détruisait le moteur
# qu'il venait de charger quand deux restaurations d'état se suivaient sur une instance neuve
# (docs/audit-2026-10-01-crash-convolveur.md). Avec le convolveur corrigé
# (provision/install-zconvo.sh), l'attendu est 0 ; avec celui du paquet x42-plugins, ~1 sur 10.
#
# CE QU'IL FAIT : N fois check-foot.py, puis il regarde si Reaper vit encore et si la vérification
# des fichiers (.rig-check.json) a bien été REJOUÉE depuis — un fichier périmé ne prouve rien.
# ⚠ Il fait TOMBER Reaper quand le défaut mord, et le relance. Jamais pendant qu'on joue.
# ⚠ `pgrep -x reaper` et pas `pgrep -f` : le motif se retrouvait dans la ligne de commande du
#   shell lui-même, et sept minutes de mesures ont tourné contre un Reaper mort sans le voir.
set -u
cd "$(dirname "$0")/.."
N="${1:-12}"
BRIDGE="${GOLEM_URL:-http://localhost:8770}"
alive() { pgrep -x reaper >/dev/null; }
restart() {
  curl -s -X POST "$BRIDGE/api/system/reaper-restart" >/dev/null; sleep 8
  for _ in $(seq 1 40); do curl -s "$BRIDGE/api/health" | grep -q '"reaper_connected":true' && break; sleep 2; done
  sleep 8; curl -s -X POST "$BRIDGE/api/system/osc-refresh" >/dev/null; sleep 2
}
crashes=0; fxfile=0
for i in $(seq 1 "$N"); do
  alive || restart
  t0=$(date +%s)
  ./tools/check-foot.py >/dev/null 2>&1
  sleep 7
  if ! alive; then crashes=$((crashes + 1)); echo "  passe $i : CRASH (voir /var/log/apport.log et journalctl -k)"; continue; fi
  if [ "$(stat -c %Y presets/.rig-check.json 2>/dev/null || echo 0)" -ge "$t0" ]; then
    python3 -c "import json,sys; sys.exit(0 if json.load(open('presets/.rig-check.json'))['ok'] else 1)" \
      || { fxfile=$((fxfile + 1)); echo "  passe $i : fichiers non chargés à la vérification"; }
  else
    echo "  passe $i : vérification NON rejouée (fichier périmé)"
  fi
done
alive || restart
echo "$N passes — crashs : $crashes — alertes fichier : $fxfile"
[ "$crashes" = 0 ]
