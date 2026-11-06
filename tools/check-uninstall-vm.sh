#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Le test qui prouve qu'une désinstallation ne laisse rien (docs/uninstall.md §7), sur la VM de provision/vm.
# En étapes, parce que l'installation et la désinstallation se font À LA MAIN (l'interface graphique, comme un
# vrai utilisateur) entre deux relevés :
#   check-uninstall-vm.sh before      relevé « machine vierge » (après vm.sh restore bare-os)
#   check-uninstall-vm.sh installed   relevé après l'installation (ce que l'installation a posé : diff avec before)
#   check-uninstall-vm.sh after       relevé après la désinstallation, puis le VERDICT (tools/uninstall-judge.py) :
#                                     chaque différence avec before rangée en (a) montée de version d'un paquet de
#                                     base, (b) gardé exprès ou par choix, (c) vraie trace -> code 1
# Les relevés vont dans ~/.cache/golem-vm/footprint/ (avec plan.json, owners.txt, links.txt, autoremove.txt et un fichier par
# classe : upgraded.txt, kept.txt, leftovers.txt). Seule la VM est touchée — et rien n'y est écrit : le plan et
# `apt-get -s` ne font que lire.
#
# --win (docs/uninstall.md §9.6) : la même chose sur la VM Windows de provision/vm/win.sh (partir de `bare-windows`) :
#   check-uninstall-vm.sh --win before|installed|after
# Le relevé est tools/footprint.ps1 (lecture seule), qui voyage par l'entrée standard de `win.sh ps` ; le plan est
# lu par le moteur INSTALLÉ dans la VM (python de golem.cmd, `uninstall.py plan --json`, lecture seule) ; le
# verdict est celui de tools/uninstall-judge.py judge --win. Relevés dans ~/.cache/golem-vm/footprint-win/. `after`
# relève aussi (lecture seule) tes VRAIS choix (chosen.txt : le journal de la désinstallation, ou les select-*.json)
# et le journal du veilleur d'après fermeture (after-uninstall.log).
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
VM="$HERE/provision/vm/vm.sh"
OUT="$HOME/.cache/golem-vm/footprint"
WIN=0
if [ "${1:-}" = "--win" ]; then WIN=1; shift; fi
step="${1:-}"

if [ "$WIN" = 1 ]; then
  VMW="$HERE/provision/vm/win.sh"
  OUT="$HOME/.cache/golem-vm/footprint-win"; mkdir -p "$OUT"
  # le script voyage par stdin : une ligne PowerShell (EncodedCommand, courte) le lit et l'exécute — un script long
  # en -EncodedCommand dépasserait la ligne de commande de cmd.exe (8191 caractères)
  RUNSTDIN='$s = [Console]::In.ReadToEnd(); & ([scriptblock]::Create($s))'
  grabw() {
    # la transmission par ssh est capricieuse (un « Complété » vide, ou un blocage, 2026-10-16) : un second essai,
    # chacun borné dans le temps
    # d'abord le script DÉJÀ dans la VM (win.sh push le met dans C:\golem\tools) : -File vers un fichier, puis on le lit —
    # l'envoi par l'entrée standard de ssh bloquait une fois sur deux (2026-10-16) ; il ne sert plus qu'en secours
    timeout 300 "$VMW" ps 'if (Test-Path C:\golem\tools\footprint.ps1) { $o = "$env:TEMP\golem-footprint.txt"; powershell -NoProfile -ExecutionPolicy Bypass -File C:\golem\tools\footprint.ps1 | Out-File -Encoding utf8 $o; Get-Content -Raw $o; Remove-Item $o }' \
      | tr -d '\r' | sed '1s/^\xEF\xBB\xBF//' > "$OUT/$1.txt"
    if ! grep -q '^## ' "$OUT/$1.txt"; then
      for _try in 1 2; do
        timeout 300 "$VMW" ps "$RUNSTDIN" < "$HERE/tools/footprint.ps1" | tr -d '\r' > "$OUT/$1.txt"
        grep -q '^## ' "$OUT/$1.txt" && break
      done
    fi
    # un relevé VIDE n'est pas un relevé : il passait pour un succès (2026-10-16, ssh juste après un démarrage)
    grep -q '^## ' "$OUT/$1.txt" || { echo "✗ relevé $1 vide ou illisible — relance (la VM vient peut-être de démarrer)" >&2; exit 1; }
    echo "· relevé $1 : $(grep -c . "$OUT/$1.txt") lignes → $OUT/$1.txt"
  }
  # le moteur INSTALLÉ, avec le Python de golem.cmd (celui de base : `uninstall.py plan` ne touche à rien)
  PLANPS=$(cat <<'PS'
$c = Join-Path $env:USERPROFILE 'golem\golem.cmd'
$m = Select-String -LiteralPath $c -Pattern '^"([^"]+)" -m provision\.desktop start' | Select-Object -First 1
if (-not $m) { exit 3 }
$py = $m.Matches[0].Groups[1].Value -replace 'pythonw\.exe$', 'python.exe'
& $py (Join-Path $env:USERPROFILE 'golem\provision\uninstall.py') plan --json
PS
)
  # ce que l'utilisateur a VRAIMENT choisi (lecture seule) : le journal de la désinstallation, à côté de la sauvegarde
  # (une ligne par élément traité, toutes les tentatives), sinon les select-<n>.json d'une copie du désinstallateur
  # restée dans %TEMP% ; rien = le juge prend les choix par défaut du plan (et le dit)
  CHOSENPS=$(cat <<'PS'
$logs = @(Get-ChildItem -Path $env:USERPROFILE -Filter 'golem-backup-*' -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Filter 'uninstall-*.log' -ErrorAction SilentlyContinue } |
    Sort-Object LastWriteTime)
if ($logs.Count) { Get-Content -LiteralPath $logs[-1].FullName | ForEach-Object { "LOG $_" }; exit 0 }
$sel = @(Get-ChildItem -Path $env:TEMP -Filter 'golem-uninstaller-*' -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ChildItem -LiteralPath $_.FullName -Filter 'select-*.json' -ErrorAction SilentlyContinue })
foreach ($f in $sel) { "SELECT " + ((Get-Content -Raw -LiteralPath $f.FullName) -replace "`r?`n", ' ') }
PS
)
  # le journal du veilleur (Python désinstallé, copie effacée après la fermeture : installer/after_exit_win.py)
  AFTERPS=$(cat <<'PS'
Get-ChildItem -Path $env:TEMP -Filter 'golem-after-uninstall-*.log' -ErrorAction SilentlyContinue | Sort-Object LastWriteTime |
    ForEach-Object { "== $($_.FullName)"; Get-Content -LiteralPath $_.FullName }
PS
)
  case "$step" in
    before)    grabw before
               rm -f "$OUT/plan.json" ;;
    installed) grabw installed
               if "$VMW" ps "$PLANPS" > "$OUT/plan.json.tmp" 2>/dev/null && python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$OUT/plan.json.tmp" 2>/dev/null; then
                 mv "$OUT/plan.json.tmp" "$OUT/plan.json"; echo "· plan de désinstallation → $OUT/plan.json"
               else
                 rm -f "$OUT/plan.json.tmp" "$OUT/plan.json"; echo "⚠ plan de désinstallation illisible : le verdict ne saura pas ce que tu as gardé"
               fi
               echo "· ce que l'installation a posé :"
               diff "$OUT/before.txt" "$OUT/installed.txt" | grep -E '^[<>]' | sed 's/^/    /' | head -400 || true ;;
    after)     grabw after
               vmhome=$("$VMW" ps 'Write-Output $env:USERPROFILE' | tr -d '\r')
               "$VMW" ps "$CHOSENPS" 2>/dev/null | tr -d '\r' > "$OUT/chosen.txt" || true
               if [ -s "$OUT/chosen.txt" ]; then echo "· tes choix relevés dans la VM → $OUT/chosen.txt"
               else echo "⚠ ni journal de désinstallation ni sélection dans la VM : le verdict prend les choix par défaut"; fi
               "$VMW" ps "$AFTERPS" 2>/dev/null | tr -d '\r' > "$OUT/after-uninstall.log" || true
               if [ -s "$OUT/after-uninstall.log" ]; then
                 echo "· le veilleur d'après fermeture (Python, copie du désinstallateur) → $OUT/after-uninstall.log :"
                 sed 's/^/    /' "$OUT/after-uninstall.log"
               fi
               rc=0
               python3 "$HERE/tools/uninstall-judge.py" judge --win "$OUT/before.txt" "$OUT/after.txt" --out "$OUT" \
                 --plan "$OUT/plan.json" --home "$vmhome" --chosen "$OUT/chosen.txt" || rc=$?
               exit "$rc" ;;
    *) echo "usage: $0 --win before|installed|after" >&2; exit 2 ;;
  esac
  exit 0
fi
mkdir -p "$OUT"
grab() {   # le script voyage par stdin : rien à pousser dans la VM, et le golem peut y être absent
  "$VM" ssh 'bash -s' < "$HERE/tools/footprint.sh" > "$OUT/$1.txt"
  echo "· relevé $1 : $(grep -c . "$OUT/$1.txt") lignes → $OUT/$1.txt"
}
case "$step" in
  before)    grab before
             rm -f "$OUT/plan.json"          # un plan d'un cycle précédent mentirait au verdict
             ;;
  installed) grab installed
             # rien du dossier personnel ne doit appartenir à root (SWS créait ~/.config à root, 2026-10-15)
             rootown=$("$VM" ssh 'find ~ -xdev -user root -printf "%p\n" 2>/dev/null | head -20')
             if [ -n "$rootown" ]; then echo "✗ fichiers à root dans le dossier personnel :"; echo "$rootown" | sed 's/^/    /'; fi
             # le plan, relevé AVANT la désinstallation : ce que le désinstallateur proposera (le juge en a besoin pour
             # reconnaître ce que l'utilisateur a choisi de garder). Le moteur voyage par stdin, comme footprint.sh.
             if "$VM" ssh 'python3 - plan --json' < "$HERE/provision/uninstall.py" > "$OUT/plan.json.tmp" 2>/dev/null; then
               mv "$OUT/plan.json.tmp" "$OUT/plan.json"; echo "· plan de désinstallation → $OUT/plan.json"
             else
               rm -f "$OUT/plan.json.tmp" "$OUT/plan.json"; echo "⚠ plan de désinstallation illisible : le verdict ne saura pas ce que tu as gardé"
             fi
             echo "· ce que l'installation a posé :"
             diff "$OUT/before.txt" "$OUT/installed.txt" | grep -E '^[<>]' | sed 's/^/    /' | head -400 || true ;;
  after)     grab after
             JUDGE=(python3 "$HERE/tools/uninstall-judge.py")
             # les faits que seule la VM connaît (lecture seule) : à qui appartiennent les fichiers apparus, leurs
             # dossiers parents sous /etc et les fichiers des unités apparues (dpkg -S), où pointent les liens apparus
             # sous /etc (readlink -f : un lien de /etc/systemd ou /etc/rc?.d sert le paquet de sa cible), et ce
             # qu'apt retirerait encore en autoremove (simulation : rien n'est retiré). L'état des paquets (installé
             # ou purgé) est déjà dans le relevé (## packages).
             "${JUDGE[@]}" new-paths "$OUT/before.txt" "$OUT/after.txt" > "$OUT/new-paths.txt"
             "${JUDGE[@]}" new-links "$OUT/before.txt" "$OUT/after.txt" > "$OUT/new-links.txt"
             : > "$OUT/links.txt"
             if [ -s "$OUT/new-links.txt" ]; then
               "$VM" ssh 'while IFS= read -r p; do printf "%s\t%s\n" "$p" "$(readlink -f -- "$p")"; done' \
                 < "$OUT/new-links.txt" > "$OUT/links.txt" || true
             fi
             { cat "$OUT/new-paths.txt"; cut -f2 "$OUT/links.txt" | grep . || true; } | sort -u > "$OUT/owner-queries.txt"
             : > "$OUT/owners.txt"
             if [ -s "$OUT/owner-queries.txt" ]; then
               "$VM" ssh 'xargs -r -d "\n" dpkg -S 2>/dev/null' < "$OUT/owner-queries.txt" > "$OUT/owners.txt" || true
             fi
             "$VM" ssh 'LC_ALL=C apt-get -s autoremove --purge 2>/dev/null' > "$OUT/autoremove.txt" || true
             vmhome=$("$VM" ssh 'printf %s "$HOME"')
             # ⚠ pas de `if diff … | grep` : sous pipefail, le code 1 de diff (= « il y a des différences ») faisait
             # passer le test pour faux et le verdict disait « rien ne reste » sur 55 000 lignes (2026-10-15). Le
             # juge rend son code lui-même : 0 propre, 1 de vraies traces, 2 relevés incomparables.
             rc=0
             "${JUDGE[@]}" judge "$OUT/before.txt" "$OUT/after.txt" --out "$OUT" --plan "$OUT/plan.json" \
               --owners "$OUT/owners.txt" --autoremove "$OUT/autoremove.txt" --home "$vmhome" \
               --links "$OUT/links.txt" || rc=$?
             exit "$rc" ;;
  *) echo "usage: $0 [--win] before|installed|after" >&2; exit 2 ;;
esac
