#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Télécharge les modèles NAM / IR référencés dans library/components.json vers assets/.
# Les captures tierces ne sont JAMAIS dans Git : ce script les récupère depuis leur `source`.
#
# Statut : amorce. Lit les `source:` http(s) directs. Les sources tone3000:/guitarml
# (sans URL directe stable) sont à compléter avec l'URL de download réelle dans le JSON.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
COMP="$ROOT/library/components.json"
. "$HERE/lib-fetch.sh"      # fetch_verified : empreintes épinglées (packs livrés)
command -v jq >/dev/null || { echo "jq requis : sudo apt install jq"; exit 1; }

# Un asset téléchargé doit être le BON format, pas une page HTML déguisée
# (URL de page tone3000 ≠ URL de fichier — corruption silencieuse trouvée en VM).
valid_asset() {  # $1 = chemin : .nam = JSON ('{'), IR .wav = RIFF
  case "$1" in
    *.nam)  [ "$(head -c1 "$1")" = "{" ] ;;
    *.wav)  head -c4 "$1" | grep -q RIFF ;;
    *)      ! head -c15 "$1" | grep -qi "<!doctype\|<html" ;;
  esac
}

echo "Lecture de $COMP"
jq -r '(.amps[]?, .cabs[]?, .pedals[]?) | select(.file and .source) | [.id, .file, .source] | @tsv' "$COMP" |
while IFS=$'\t' read -r id file source; do
  dest="$ROOT/$file"
  if [ -f "$dest" ]; then echo "  ✓ $id (déjà présent)"; continue; fi
  case "$source" in
    http://*|https://*)
      mkdir -p "$(dirname "$dest")"
      echo "  ↓ $id ← $source"
      if ! curl -fsSL "$source" -o "$dest"; then
        echo "    ✗ échec de téléchargement : $source"
      elif ! valid_asset "$dest"; then
        rm -f "$dest"
        echo "    ✗ contenu invalide (page HTML ? URL de page au lieu du fichier) — SUPPRIMÉ."
        echo "      → installer via l'app (Library ▸ New TONE3000) ou corriger l'URL dans components.json"
      fi
      ;;
    *)
      echo "  ⏭ $id : source non-directe ($source) — renseigner une URL http(s) dans components.json"
      ;;
  esac
done
echo "Terminé. (Rien de tout ceci n'entre dans Git — voir assets/.gitignore.)"

# ── PACKS OPTIONNELS (installateur, docs/installer.md §3 écran Taille) : GOLEM_PACKS="base,piano,drums" ;
#    absent = tout. `di` = les DI de référence GoleM (requis, GitHub Releases), `piano` = Salamander,
#    `guitar` = Shinyguitar (la pompe du bloc Standard),
#    `drums` = Aasimonster. AUCUNE capture d'ampli n'est livrée (2026-09-09) : le rack neuf est vide.
PACKS="${GOLEM_PACKS:-di,piano,drums,guitar}"
has_pack() { case ",$PACKS," in *",$1,"*) return 0 ;; *) return 1 ;; esac; }

# ── L'AVANCEMENT pour l'installateur graphique (installer/phases.py, VM 2026-10-23) : la phase « Sounds » estimait à
#    1,85 Mo/s et en faisait 5 — elle annonçait 18 min quand il en restait 1,5. On dit les Mo téléchargés toutes les
#    5 s ; l'écran en tire le débit RÉEL. Muet dans un terminal (GOLEM_INSTALLER absent), comme install.sh.
mark() { if [ "${GOLEM_INSTALLER:-}" = 1 ]; then echo "@@$*"; fi; }
SFZ_DIR="$ROOT/library/sfz"; DK_DIR="$ROOT/library/drumkits"
# Mo TÉLÉCHARGÉS (Content-Length des archives épinglées, 2026-10-23) — pas la place sur disque de components.json
SOUNDS_TODO=()
has_pack piano  && [ ! -d "$SFZ_DIR/SalamanderGrandPiano-SFZ+FLAC-V3+20200602" ] && SOUNDS_TODO+=("piano:707")
has_pack guitar && [ ! -d "$SFZ_DIR/Shinyguitar" ] && SOUNDS_TODO+=("guitar:351")
has_pack drums  && [ ! -d "$DK_DIR/aasimonster2" ] && SOUNDS_TODO+=("drums:2304")
SOUNDS_TOTAL=0; for x in "${SOUNDS_TODO[@]}"; do SOUNDS_TOTAL=$((SOUNDS_TOTAL + ${x#*:})); done
SOUNDS_DONE=0; SOUNDS_N=0
# fetch_watched <url> <dest> <Mo> <libellé anglais> : fetch_verified, avec l'avancement dit pendant le téléchargement
fetch_watched() {
  local url="$1" dest="$2" mb="$3" label="$4" pid rc=0
  SOUNDS_N=$((SOUNDS_N + 1))
  mark sub "$label — $SOUNDS_N of ${#SOUNDS_TODO[@]}"
  if [ "${GOLEM_INSTALLER:-}" = 1 ] && [ "$SOUNDS_TOTAL" -gt 0 ]; then
    ( while sleep 5; do
        sz=$(stat -c %s "$dest.part" 2>/dev/null || echo 0)
        mark progress $((SOUNDS_DONE + sz / 1048576)) "$SOUNDS_TOTAL"
      done ) &
    pid=$!
    disown "$pid" 2>/dev/null || true       # pas de « Complété » de bash dans la trace quand il s'arrête
  fi
  fetch_verified "$url" "$dest" || rc=$?
  if [ -n "${pid:-}" ]; then
    # le `sleep` du veilleur par son PID (jamais par motif) : orphelin, il tiendrait la sortie (cf. install.sh)
    pkill -P "$pid" 2>/dev/null || true; kill "$pid" 2>/dev/null || true
  fi
  SOUNDS_DONE=$((SOUNDS_DONE + mb)); mark progress "$SOUNDS_DONE" "$SOUNDS_TOTAL"
  return "$rc"
}

# ── DI de référence GoleM (guitare, basse) : le SEUL son livré — les previews de presets s'en re-ampent
#    (docs/preset-preview.md). Publié en release GitHub `di-refs-v1` ; tant qu'il n'est pas publié, on le dit.
# library/di-refs : là où le bridge les lit (bridge/config.py DI_REFS_DIR) — c'était library/di, qu'il ne lit pas.
# PAS ENCORE ENREGISTRÉES (2026-10-23) : la release n'existe pas, son URL n'est pas épinglée — on le dit sans
# tenter un téléchargement voué au refus (la ligne « ✗ non épinglé — refusé » faisait croire à une panne).
DI_DIR="$ROOT/library/di-refs"; DI_URL="${GOLEM_DI_URL:-https://github.com/Goldoralf/golem-binaries/releases/download/di-refs-v1/golem-di-refs-v1.tar.gz}"
if ! has_pack di; then
  echo "  ⏭ DI de référence : pack « di » non demandé (GOLEM_PACKS=$PACKS)"
elif ! awk -v u="$DI_URL" '$1 !~ /^#/ && $2 == u { f=1 } END { exit !f }' "$GOLEM_SUMS" 2>/dev/null; then
  echo "  ⏭ DI de référence : pas encore publiées (docs/preset-preview.md) — les previews de presets attendront"
elif ls "$DI_DIR"/*/*.wav "$DI_DIR"/*/*.flac >/dev/null 2>&1; then
  echo "  ✓ DI de référence déjà présentes ($DI_DIR)"
else
  echo "  ↓ DI de référence GoleM ← $DI_URL"
  mkdir -p "$DI_DIR" && cd "$DI_DIR"
  if fetch_verified "$DI_URL" di.tgz; then tar -xzf di.tgz && rm -f di.tgz && echo "    ✓ DI de référence"
  else rm -f di.tgz; echo "    ⚠ indisponible (pas encore publiée sur GitHub Releases, ou pas encore épinglée dans downloads.sha256) — les previews attendront ; rejouer fetch-assets.sh plus tard"; fi
fi

# ── Piano SFZ : Salamander Grand v3 (bloc piano, lane Keys — P1 claviers) ────
if ! has_pack piano; then
  echo "  ⏭ Salamander : pack « piano » non demandé (GOLEM_PACKS=$PACKS)"
elif [ ! -d "$SFZ_DIR/SalamanderGrandPiano-SFZ+FLAC-V3+20200602" ]; then
  echo "  ↓ Salamander Grand v3 (~450 MB)"
  mkdir -p "$SFZ_DIR" && cd "$SFZ_DIR"
  fetch_watched "https://freepats.zenvoid.org/Piano/SalamanderGrandPiano/SalamanderGrandPiano-SFZ+FLAC-V3+20200602.tar.gz" salamander.tar.gz 707 "Piano (Salamander)" \
    && tar -xzf salamander.tar.gz && rm salamander.tar.gz && echo "    ✓ Salamander v3"
fi

# ── Guitare SFZ : Shinyguitar (Karoryfer, CC0) — la pompe manouche du bloc Standard ────
# Une archtop prise au micro et au capteur ; golem_chordseq.lua n'en joue que le micro, deux voix
# (docs/standards.md §10). Son propre pack : il est proposé sous Windows et macOS, le piano pas encore.
# Windows/macOS le téléchargent par installer/desktop_steps.py (même URL, même empreinte).
if ! has_pack guitar; then
  echo "  ⏭ Shinyguitar : pack « guitar » non demandé (GOLEM_PACKS=$PACKS)"
elif [ ! -d "$SFZ_DIR/Shinyguitar" ]; then
  echo "  ↓ Shinyguitar (~350 MB)"
  mkdir -p "$SFZ_DIR" && cd "$SFZ_DIR"
  fetch_watched "https://github.com/sfzinstruments/karoryfer.shinyguitar/releases/download/v1.001/Karoryfer.Shinyguitar.v1.001.zip" shinyguitar.zip 351 "Guitar (Shinyguitar)" \
    && unzip -q shinyguitar.zip && rm shinyguitar.zip && echo "    ✓ Shinyguitar"
fi

# ── Kit DrumGizmo : The Aasimonster v2.1 (bloc drums, moteur `drumgizmo`) ────
# 2,3 Go, CC-BY 4.0 — batterie MULTI-MICROS (14 micros + trigger/module = 16 canaux),
# avec la diaphonie réelle entre les micros. C'est ce qui la sépare d'avldrums.
# Attribution exigée par la licence : voir library/drumkits/CREDITS.md.
if ! has_pack drums; then
  echo "  ⏭ Aasimonster : pack « drums » non demandé (GOLEM_PACKS=$PACKS)"
elif [ ! -d "$DK_DIR/aasimonster2" ]; then
  echo "  ↓ DrumGizmo — The Aasimonster v2.1 (~2,3 Go)"
  mkdir -p "$DK_DIR" && cd "$DK_DIR"
  fetch_watched "https://drumgizmo.org/kits/Aasimonster/aasimonster2_1.zip" aasimonster.zip 2304 "Drums (Aasimonster)" \
    && unzip -q aasimonster.zip && rm aasimonster.zip && echo "    ✓ Aasimonster v2.1"
fi

# ── Grilles de standards ────────────────────────────────────────────────────
# RIEN À RAPATRIER ICI. Le rack ne connaît pas de catalogue de standards : il reçoit ce que
# golem.fm lui synchronise (docs/standards.md, Addendum 3), via GET /api/ext/standards.
# Pour travailler avant que cet endpoint existe : ./tools/seed-standards.py
