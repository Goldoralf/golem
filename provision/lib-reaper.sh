# SPDX-License-Identifier: GPL-3.0-or-later
# Le REAPER DE CE RACK (2026-11-06), partagé par start.sh et reload.sh : un processus « reaper » qui n'est ni un zombie
# ni le REAPER d'un banc — check-rig-materialize et shell_snapshot lancent le leur avec -cfgfile. `pgrep -x reaper` seul
# voyait le zombie laissé par un banc : start.sh croyait REAPER ouvert et ne le relançait pas. Même règle côté bridge :
# routes_system._rack_reaper_pids.
rack_reaper_pids() {
  local p
  for p in $(pgrep -x reaper); do
    [ "$(awk '{print $3}' "/proc/$p/stat" 2>/dev/null)" = Z ] && continue
    tr '\0' ' ' < "/proc/$p/cmdline" 2>/dev/null | grep -q -- '-cfgfile' && continue
    echo "$p"
  done
}

# Arrête le REAPER de ce rack et attend sa mort réelle (il sauve sa config avant de quitter) — 15 s au plus.
stop_rack_reaper() {
  local pids i
  pids=$(rack_reaper_pids)
  [ -n "$pids" ] || return 0
  # shellcheck disable=SC2086
  kill $pids 2>/dev/null || true
  for i in $(seq 1 50); do [ -z "$(rack_reaper_pids)" ] && return 0; sleep 0.3; done
  echo "⚠ REAPER ne s'est pas arrêté en 15 s"
  return 1
}

# LA VERSION DES SCRIPTS QUE REAPER A CHARGÉS : l'empreinte git du dossier reaper/ (Lua, JSFX) au lancement de REAPER,
# dans presets/.reaper-tree. reload.sh la compare au commit courant : une mise à jour (git checkout d'une release) ou un
# pull qui change reaper/ relance REAPER avec le bridge — sinon ses boucles gardaient l'ancien code. Une retouche non
# commitée d'un Lua ne compte pas (même commit) : elle se recharge à la main (CLAUDE.md, règle 1). Sans git : rien.
reaper_tree() { git -C "$1" rev-parse -q --verify "HEAD:reaper" 2>/dev/null; }
record_reaper_tree() {
  local t; t=$(reaper_tree "$1") || return 0
  [ -n "$t" ] && printf '%s\n' "$t" > "$1/presets/.reaper-tree" 2>/dev/null || true
}
reaper_scripts_stale() {
  local cur rec; cur=$(reaper_tree "$1") || return 1
  [ -n "$cur" ] || return 1
  rec=$(cat "$1/presets/.reaper-tree" 2>/dev/null)
  [ "$rec" != "$cur" ]                       # rien de noté (REAPER lancé par une version d'avant) = à relancer
}
