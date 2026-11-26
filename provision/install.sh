#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — provisioning maître.
# Idempotent : rejouable sans casser. Cible : Ubuntu 24.04 (ROG alpha & rack final).
#
#   ./provision/install.sh            tout : système, Reaper, plugins, bridge, sons (~1 Go)
#   ./provision/install.sh --light    idem SANS les gros téléchargements (piano, NAM/IR)
#   ./provision/install.sh --engine=reaper   REAPER en plus du Golem Engine, et moteur par défaut
#                                            (sans --engine : le Golem Engine seul — docs/install-v2.md)
#
# Le --light sert au poste de DÉV : le rack, lui, veut tout. Sans les sons, le rig démarre et
# l'app tourne, mais les blocs piano/ampli chargeront dans le vide — c'est dit à la fin.
set -euo pipefail
LIGHT=0
LIGHT=0; PROFILE="${GOLEM_PROFILE:-}"; ENGINE="${GOLEM_ENGINE:-}"
for a in "$@"; do case "$a" in
  --light) LIGHT=1 ;;
  --engine=*) ENGINE="${a#--engine=}" ;;
  --profile=*) PROFILE="${a#--profile=}" ;;   # OBSOLÈTE (2026-10-06) : ignoré, dit plus bas
  --packs=*) export GOLEM_PACKS="${a#--packs=}" ;;   # di,piano,drums,guitar — lu par fetch-assets.sh
esac; done
# --profile : PLUS DE PROFIL (docs/installer.md §4, 2026-10-06). Une installation, deux usages —
# `golem desktop` et `golem server` ; la boîte dédiée est une option : `golem autostart on`.
if [ -n "$PROFILE" ]; then
  echo "⚠ --profile=$PROFILE ignoré : GoleM n'a plus qu'une installation (golem desktop / golem server)."
  echo "  Boîte dédiée (golem server au boot, sans session) : golem autostart on"
fi
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# --engine (docs/install-v2.md, 2026-11-18) : le Golem Engine est TOUJOURS installé ; REAPER est une option.
#   --engine=reaper  REAPER est installé aussi, et devient le moteur par défaut ;
#   --engine=ardour  le Golem Engine seul (REAPER n'est pas installé) ;
#   sans --engine    une installation neuve prend le Golem Engine s'il a pu être posé, sinon REAPER ; une machine qui
#                    a déjà choisi (config/engine.json) garde son choix, et son REAPER.
# Le choix n'est ÉCRIT qu'après la pose des moteurs (write_engine_choice, plus bas) : bridge/engines.py n'accepte
# qu'un moteur disponible, et le Golem Engine ne l'est qu'une fois posé.
case "$ENGINE" in ""|reaper|ardour) ;; *) echo "✗ --engine: unknown engine « $ENGINE » (reaper, ardour)"; exit 1 ;; esac
PRIOR_ENGINE="$(python3 -c 'import json,sys
try: print(json.load(open(sys.argv[1])).get("engine") or "")
except Exception: print("")' "$HERE/../config/engine.json" 2>/dev/null || true)"
write_engine_choice() {  # $1 = id voulu
  python3 - "$HERE/.." "$1" <<'PYENG'
import importlib.util, os, sys
root, want = os.path.abspath(sys.argv[1]), sys.argv[2]
spec = importlib.util.spec_from_file_location("golem_engines", os.path.join(root, "bridge", "engines.py"))
E = importlib.util.module_from_spec(spec); spec.loader.exec_module(E)
try:
    eid = E.write_choice(want or E.default_id(root), root=root, set_by="install.sh")
except ValueError as e:
    ok = ", ".join(x["id"] for x in E.descriptors(root) if x["available"])
    sys.exit(f"✗ --engine: {e} (available: {ok})")
print(f"→ moteur audio « {eid} » (config/engine.json)")
PYENG
}
log() { printf '\n\033[1;36m▶ %s\033[0m\n' "$*"; }
# L'INSTALLATEUR GRAPHIQUE lit ces marqueurs (installer/phases.py) : la phase en cours, sa sous-ligne, un manque non
# fatal dit en anglais sur l'écran (la trace brute — warnings de compilation — fait paniquer, 2026-10-23). Dans un
# terminal (GOLEM_INSTALLER absent) ils ne s'impriment pas : la sortie reste celle d'avant.
mark() { if [ "${GOLEM_INSTALLER:-}" = 1 ]; then echo "@@$*"; fi; }
# lancé à la main (hors installateur graphique) : dire qu'il existe un chemin avec des écrans (2026-11-03)
if [ "${GOLEM_INSTALLER:-}" != 1 ]; then
  echo "Tip: ./install-linux.sh does all of this with screens (and sets up the golem command and icons)."
fi
# soft_fail <retry-id> <message terminal> <message écran (anglais)> — retry-id = le ↻ de l'écran (installer/platform_linux.py RETRY)
soft_fail() { echo "  ⚠ $2"; mark "warn $1|$3"; }
# le REÇU D'INSTALLATION (docs/uninstall.md §2) : ce que l'install crée, et l'état d'avant — hors du dossier
. "$HERE/lib-receipt.sh"
receipt set-root "$HERE/.." --release "$(git -C "$HERE/.." describe --tags --always 2>/dev/null || echo unknown)"

# ── SUDO : on le demande UNE FOIS, au début, et on tient le ticket ────────────────────────
# Neuf appels `sudo` sont répartis sur tout le déroulé, dont certains APRÈS plusieurs minutes
# de téléchargement. Le cache sudo expire au bout de ~15 min : l'install se bloquait donc en
# plein milieu, à réclamer un mot de passe que personne ne regardait. Invisible en VM (cloud-init
# donne NOPASSWD), certain sur un vrai rack.
# ⚠ ON ESSAIE D'ABORD SANS RIEN DEMANDER. `sudo -v` exige un TERMINAL même quand l'utilisateur
# a NOPASSWD (vérifié en VM) : l'utiliser d'emblée cassait toute install non interactive —
# provisioning automatisé, ssh sans tty, image de rack. On ne demande que si c'est nécessaire.
# Sous l'installateur graphique, `sudo` est un shim qui ajoute -A (installer/platform_linux.py _askpass) : sudo-rs
# (Ubuntu 25.10+) n'utilise l'askpass qu'avec -A, et `sudo -v` attendait sinon un mot de passe sur un terminal que
# personne ne regardait (2026-11-03). Un échec malgré tout est DIT à l'écran, en anglais, au lieu d'un silence.
if ! sudo -n true 2>/dev/null; then
  if ! sudo -v; then
    echo "✗ sudo requis (paquets, limites temps-réel, plugins système)."
    mark "warn |golem could not get administrator rights (sudo refused the password, or your account is not an administrator). Check the password, then tap Retry."
    exit 1
  fi
fi
# >/dev/null : la boucle tuée en sortie laisse son `sleep 60` orphelin ; s'il tenait NOTRE sortie, l'installateur
# graphique attendait la fin du tuyau jusqu'à une minute après « Provisioning terminé » (53 s mesurées, VM 2026-10-23)
while true; do sudo -n true 2>/dev/null; sleep 60; kill -0 "$$" 2>/dev/null || exit; done >/dev/null 2>&1 &
SUDO_KEEPALIVE=$!
trap 'kill "$SUDO_KEEPALIVE" 2>/dev/null || true' EXIT

# --- 1. Paquets apt ----------------------------------------------------------
mark phase packages
log "Paquets apt (packages.txt)"
# ⚠ `-o DPkg::Lock::Timeout=300` sur TOUS les apt : sur une machine fraîchement démarrée,
# `unattended-upgrades` tient le verrou dpkg pendant plusieurs minutes. Sans ce délai, apt
# rend la main aussitôt (E: Could not get lock) et l'install meurt en 100 — c'est-à-dire
# qu'elle échoue systématiquement au PREMIER essai sur un rack neuf, puis marche au second.
# Le pire des symptômes : intermittent, donc mis sur le compte de la malchance.
# ⚠ NOTRE dépôt tiers ne survit pas entre deux installs (validation VM 2026-09-09). La clé OBS de
# sfizz a expiré en amont : le fichier laissé par une install précédente fait échouer TOUS les
# `apt-get update` de la machine — le nôtre, celui des plugins, et ceux de l'utilisateur, six mois
# plus tard, pour une raison illisible. On le retire ; install-sfizz.sh le recrée s'il en a besoin,
# et le retire lui-même s'il ne marche pas.
sudo rm -f /etc/apt/sources.list.d/sfizz.list /etc/apt/trusted.gpg.d/sfizz.gpg
# ⚠ `update` NON FATAL (validation VM 2026-09-09) : UN dépôt tiers en panne — la clé de sfizz a
# expiré en amont — fait rendre 100 à apt-get update, et l'installation ENTIÈRE mourait à la
# première ligne, pour une raison illisible. L'index disponible suffit ; c'est le manque d'un
# paquet ESSENTIEL qui doit être fatal, et il l'est plus bas, avec son nom.
sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 update -qq \
  || echo "  ⚠ un dépôt a échoué (voir ci-dessus) — on continue avec l'index disponible"
# la liste, résolue contre l'index (provision/lib-packages.sh) : un paquet OPTIONNEL (« nom? ») qu'une version
# d'Ubuntu a retiré est écarté et dit ; un ESSENTIEL absent arrête l'install en le nommant. Avant (Ubuntu 26.04,
# 2026-11-03), UN paquet disparu faisait mourir l'unique `apt-get install` — et l'install entière, en phase 1.
. "$HERE/lib-packages.sh"
golem_packages_resolve "$HERE/packages.txt"
for p in "${PKGS_SKIPPED[@]}"; do
  soft_fail "" "paquet optionnel « $p » absent de cette distribution — écarté" \
    "Optional package $p is not available on this system — skipped (the blocks that use it stay silent)"
done
if [ "${#PKGS_MISSING[@]}" -gt 0 ]; then
  echo "✗ paquets essentiels absents de cette distribution : ${PKGS_MISSING[*]}"
  echo "  (apt-cache policy <paquet> : aucun candidat — dépôt « universe » activé ? version d'Ubuntu prise en charge ?)"
  exit 1
fi
# reçu : photo des paquets JUSTE avant, différence juste après — un paquet déjà là n'est pas à nous
# (apt-requested reçoit la liste FILTRÉE : un paquet écarté n'a jamais été demandé, le reçu ne doit pas le dire)
receipt apt-snapshot before
receipt apt-requested "${PKGS[@]}"
# jackd2 (tiré par les plugins) demande s'il doit écrire SES limites temps réel : non, les nôtres sont posées plus bas
echo "jackd2 jackd/tweak_rt_limits boolean false" | sudo debconf-set-selections
sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 -o Dpkg::Options::=--force-confdef -o Dpkg::Options::=--force-confold install -y "${PKGS[@]}"
receipt apt-snapshot after

# --- 2. Temps-réel : groupe audio + limits ----------------------------------
mark phase realtime
log "Temps-réel (groupe audio + rtprio/memlock)"
# reçu : l'utilisateur était-il DÉJÀ dans `audio` ? (la désinstallation ne l'en retire que s'il n'y était pas)
# (pas de pipeline sous pipefail : un grep -q qui sort tôt ferait mentir le test)
case " $(id -nG "$USER" 2>/dev/null) " in
  *" audio "*) receipt prior audio_group true ;;
  *)           receipt prior audio_group false ;;
esac
sudo usermod -aG audio "$USER"
LIMITS=/etc/security/limits.d/95-golem-audio.conf
sudo tee "$LIMITS" >/dev/null <<'EOF'
# GoleM — limites temps-réel pour les threads Reaper
@audio   -  rtprio     95
@audio   -  memlock    unlimited
EOF
receipt_add "$LIMITS" file system --owner root
echo "  → $LIMITS écrit. (Relog nécessaire pour activer ulimit -r 95)"

# gouverneur CPU basculable depuis le dashboard (bouton performance) — sudoers NOPASSWD on/off
log "Autorisation gouverneur CPU (bouton performance du dashboard)"
"$HERE/setup-perf-sudo.sh"

# Le wrapper réseau (net.sh : AP de secours, bascule WiFi, QR d'appairage) a besoin de sa
# copie root-owned et de son sudoers. Il n'était PAS appelé ici : sur un rack fraîchement
# installé, le réseau ne pouvait donc rien changer, et l'AP de secours ne se serait jamais
# levé — la panne qu'on découvre en salle de répète, sans réseau pour la diagnostiquer.
log "Autorisation réseau (net.sh : AP de secours, bascule WiFi)"
"$HERE/setup-net-sudo.sh"

# --- 3. Les moteurs audio (docs/install-v2.md) ---------------------------------
# Le Golem Engine d'abord, TOUJOURS : le moteur de golem (GPL), paquet autonome épinglé dans ~/opt/golem-engine, sans
# sudo. REAPER ensuite, seulement s'il est choisi — ou si le Golem Engine n'a pas pu être posé : golem ne reste
# jamais sans moteur.
mark phase engine
log "Golem Engine (le moteur audio de golem — précompilé)"
engine_rc=0; "$HERE/install-golem-engine.sh" || engine_rc=$?
HAVE_GOLEM_ENGINE=0; python3 "$HERE/golem_engine.py" --check >/dev/null 2>&1 && HAVE_GOLEM_ENGINE=1
WITH_REAPER=0
if [ "$ENGINE" = reaper ]; then WITH_REAPER=1
elif [ -z "$ENGINE" ] && [ "$PRIOR_ENGINE" = reaper ]; then WITH_REAPER=1     # une machine déjà sur REAPER le garde
elif [ "$HAVE_GOLEM_ENGINE" = 0 ]; then
  WITH_REAPER=1
  if [ "$engine_rc" = 1 ]; then
    soft_fail golem-engine "Golem Engine NON installé — REAPER est installé à sa place" \
      "golem's own audio engine could not be installed — REAPER is installed instead. Tap Retry."
  else
    echo "  → pas de Golem Engine pour cette machine pour l'instant : REAPER est installé"
  fi
fi
if [ "$WITH_REAPER" = 1 ]; then
  mark phase reaper
  log "Reaper"
  "$HERE/install-reaper.sh"
else
  log "REAPER — non installé (le Golem Engine est le moteur ; REAPER s'ajoute plus tard : ./provision/install.sh --engine=reaper)"
fi

# --- 4. Plugins (GitHub releases) -------------------------------------------
mark phase plugins
log "Plugins (releases GitHub : NAM, Dexed)"
"$HERE/plugins.sh"
# plugins-deb.sh (Proteus, ChowDSP BYOD) : RETIRÉ (2026-11-15) — aucun bloc ne s'en sert plus.

# golem-fx (2026-11-15, docs/golem-fx-reaper.md) : les effets de golem, release épinglée (provision/golem_fx.py VERSION) précompilée, dans
# ~/.vst3. Non fatal : sans eux, les blocs jouent leurs plugins d'origine (guitarix, Calf… restent installés).
log "golem-fx (les effets de golem — VST3 précompilés)"
"$HERE/install-golem-fx.sh" || soft_fail golem-fx "golem-fx NON installé — les blocs gardent leurs plugins d'origine" \
  "golem's own effects (golem-fx) could not be installed — the blocks play their previous plugins. Tap Retry."

# SWS : RETIRÉ de l'install (2026-09-22). Il était posé « requis par les scènes » — faux : le moteur
# de scènes est golem_rig (union materialization), LiveConfigs n'a jamais servi (audit 2026-09-21), et
# le dernier appel SWS du moteur (destination d'un send, rec-follow) passe désormais par l'API native
# P_DESTTRACK — mesuré sur le rig le 2026-09-22. `plugins-sws.sh` reste là pour qui veut le banc
# LiveConfigs ou le diagnostic MIDI étendu ; il ne s'installe plus tout seul.

# --- 4 bis. Plugins des blocs FX + sampler SFZ ------------------------------
# Ces deux-là N'ÉTAIENT PAS appelés ici (constaté le 2026-07-29 en préparant l'arrivée d'un
# second dev) : une machine fraîchement provisionnée démarrait donc SANS les effets des blocs
# ni le sampler des claviers. Un script d'install qui laisse la moitié du rig dehors n'est pas
# un script d'install.
log "Plugins LV2 des blocs FX (Calf, x42, guitarix, ZamAudio, mda…)"
sudo "$HERE/install-plugins.sh"
bash "$HERE/install-capture.sh"
# Vital / Vitalium : AUCUN paquet ne l'installe (install-plugins.sh, étape 4) — l'écran le dit, au lieu d'une ligne
# ✗ perdue dans la trace (VM 2026-10-23 : « invisible pour l'utilisateur »)
if [ ! -d "$HOME/.vst3/Vital.vst3" ] && [ ! -d "$HOME/.vst3/vitalium.vst3" ] && [ ! -d "$HOME/.lv2/vitalium.lv2" ]; then
  mark "warn |Vital is missing — the synth of the Keys lane stays silent. It needs a free vital.audio account: get it from vital.audio, golem finds it at its next start."
fi

# --- 4 ter. Chromium : LA FENÊTRE golem (2026-11-03) ---------------------------
# `golem desktop` (provision/golem) ouvre l'app en fenêtre d'application Chromium (--app, --window-size, l'échelle
# mémorisée) ; sans Chromium il retombe sur un ONGLET du navigateur par défaut, à sa taille. Aucune Ubuntu vierge ne
# l'a : Ubuntu ne le distribue qu'en snap (`chromium-browser` en apt n'est qu'un renvoi vers le snap). Non fatal.
# Debian et Mint (2026-11-03) : pas de snap (Mint le BLOQUE, nosnap.pref), mais un vrai paquet `chromium` — posé par
# apt, au reçu comme tout paquet (apt.requested ∩ apt.added : la désinstallation le propose). Le snap ensuite.
# Reçu : posé PAR NOUS seulement s'il n'était pas là (prior, le premier gagne) — la désinstallation ne retire que ça.
golem_has_chromium() {
  local x exe
  for x in chromium chromium-browser google-chrome google-chrome-stable brave-browser; do
    exe=$(command -v "$x" 2>/dev/null) || continue
    case "$x" in
      chromium*)   # le renvoi d'Ubuntu vers le snap ne compte que si le snap est là. « /snap/ » et pas « snap » : le
                   # /usr/bin/chromium de Debian est AUSSI un script, qui lance le vrai binaire de /usr/lib
        if [ "$(readlink -f "$exe")" = /usr/bin/snap ] || { [ "$(head -c 2 "$exe" 2>/dev/null)" = '#!' ] && grep -qs '/snap/' "$exe"; }; then
          [ -d /snap/chromium ] || continue
        fi ;;
    esac
    return 0
  done
  return 1
}
log "Chromium (la fenêtre golem)"
if golem_has_chromium; then
  receipt prior chromium.installed_by_golem false
  echo "  → un navigateur Chromium est déjà là"
elif CHROMIUM_DEB="$(golem_chromium_deb)"; [ -n "$CHROMIUM_DEB" ]; then
  # « prior » seulement s'il est POSÉ (le premier gagne) : un échec ici suivi d'un snap posé par l'utilisateur ne doit
  # pas faire proposer à la désinstallation de retirer SON Chromium
  receipt apt-snapshot before
  receipt apt-requested "$CHROMIUM_DEB"
  if sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=300 install -y "$CHROMIUM_DEB"; then
    receipt apt-snapshot after
    receipt prior chromium.installed_by_golem true
  else
    receipt apt-snapshot after
    soft_fail "" "Chromium NON installé (apt $CHROMIUM_DEB) — golem s'ouvrira dans un onglet, pas dans sa fenêtre" \
      "No golem window: Chromium could not be installed, so golem opens in a browser tab. Install Chromium, then start golem again."
  fi
elif command -v snap >/dev/null 2>&1 && sudo snap install chromium; then
  receipt prior chromium.installed_by_golem true
else
  soft_fail "" "Chromium NON installé — golem s'ouvrira dans un onglet, pas dans sa fenêtre" \
    "No golem window: Chromium could not be installed, so golem opens in a browser tab. Install Chromium, then start golem again."
fi

# Airwindows TapeDelay2 : RETIRÉ (2026-11-15) — le bloc Tape Delay (Airwindows) est retiré (catalogue v48).

log "sfizz (sampler SFZ — bloc piano de la lane Keys)"
# ⚠ NON FATAL (validation VM du 2026-09-09) : la clé du dépôt OBS de sfizz a expiré en amont, apt
# a rendu 100, et TOUTE l'installation est morte là — avant le bridge, avant les sons — pour UN
# bloc. Une source TIERCE qui casse ne doit jamais emporter l'install : on prévient, on continue,
# et Settings ▸ Licences ▸ Libraries dit « missing » (le manifeste connaît sfizz).
sudo "$HERE/install-sfizz.sh" || soft_fail sfizz "sfizz NON installé — le bloc piano restera muet (Settings ▸ Licences ▸ Libraries)" \
  "sfizz could not be installed — the piano of the Keys lane stays silent."

# GOLEM_INSTALLER traverse sudo (`sudo env …`) : un script qui doit COMPILER (précompilé indisponible) le dit à
# l'écran, qui allonge la phase d'autant (lib-prebuilt.sh `compiling`)
mark phase build

mark sub "IR convolver fix (cab block) — 1 of 4"
log "Convolveur d'IR corrigé (bloc cab) — compilé depuis la source avec notre patch"
# Celui du paquet x42-plugins tue Reaper ~1 fois sur 10 sur des presets rapprochés
# (docs/audit-2026-10-01-crash-convolveur.md). Non fatal comme les autres sources tierces — mais ici
# l'échec n'est PAS muet à l'usage : le bloc cab marche avec le convolveur d'apt, et il crashe.
sudo env GOLEM_INSTALLER="${GOLEM_INSTALLER:-}" "$HERE/install-zconvo.sh" || soft_fail zconvo "convolveur corrigé NON installé — celui d'apt reste en service et peut faire tomber Reaper sur des changements de preset rapprochés (Settings ▸ Licences ▸ Libraries : zeroconvo.lv2 (fixed build) = missing)" \
  "The IR convolver fix could not be built — cabs play with the standard convolver, which can stop the engine on very fast patch changes."

mark sub "NAM fix (amp and pedal blocks) — 2 of 4"
log "Ampli NAM corrigé (blocs amp / pedal NAM) — compilé depuis la source avec notre patch"
# La release v0.2.2 tue Reaper sur des changements de patch rapprochés (docs/audit-2026-10-14-crash-nam.md).
if ! sudo env GOLEM_INSTALLER="${GOLEM_INSTALLER:-}" "$HERE/install-nam.sh"; then
  if [ -f "$HOME/.lv2/neural_amp_modeler.lv2/neural_amp_modeler.so" ]; then
    soft_fail nam "NAM corrigé NON installé — la release reste en service et peut faire tomber Reaper sur des changements de patch rapprochés" \
      "The NAM fix could not be built — amps play with the standard NAM, which can stop the engine on very fast patch changes."
  else   # processeur sans AVX2/FMA et compilation ratée : install-nam.sh a retiré NAM plutôt que de laisser REAPER mourir
    soft_fail nam "NAM non compilé pour ce processeur (sans AVX2/FMA) — retiré : les blocs ampli NAM sont indisponibles" \
      "NAM could not be built for this processor — NAM amp blocks are unavailable. Run sudo ./provision/install-nam.sh again to retry."
  fi
fi

mark sub "Prisma (Grit block) — 3 of 4"
log "Prisma (bloc Grit) et les blocs spectraux (Spectral Comp, Stretch) — compilés depuis la source"
# Même règle : une source tierce qui casse ne tue pas l'install. Prisma n'était chaîné NULLE PART
# (trouvé le 2026-09-25) : un rack neuf n'avait pas de bloc Grit, et rien ne le disait.
sudo env GOLEM_INSTALLER="${GOLEM_INSTALLER:-}" "$HERE/install-prisma.sh" || soft_fail prisma "Prisma NON installé — le bloc Grit restera muet (Settings ▸ Licences ▸ Libraries)" \
  "Prisma could not be built — the Grit block stays silent."
mark sub "Spectral blocks (Spectral Comp, Stretch) — 4 of 4"
sudo env GOLEM_INSTALLER="${GOLEM_INSTALLER:-}" "$HERE/install-spectral.sh" || soft_fail spectral "blocs spectraux NON installés — Spectral Comp et Stretch resteront muets (Settings ▸ Licences ▸ Libraries)" \
  "The spectral blocks could not be built — Spectral Comp and Stretch stay silent."

# --- 5. Config Reaper : symlinks + OSC + device audio -----------------------
mark phase golem
if [ "$WITH_REAPER" = 1 ]; then
  log "Config Reaper (symlinks portables + OSC + device audio dans reaper.ini)"
  "$HERE/setup-reaper.sh"
fi
# le moteur par défaut : celui demandé ; sinon le choix déjà fait sur cette machine ; sinon le Golem Engine s'il est
# là, REAPER autrement
WANT_ENGINE="$ENGINE"
[ -z "$WANT_ENGINE" ] && WANT_ENGINE="$PRIOR_ENGINE"
if [ -z "$WANT_ENGINE" ]; then if [ "$HAVE_GOLEM_ENGINE" = 1 ]; then WANT_ENGINE=ardour; else WANT_ENGINE=reaper; fi; fi
[ "$WANT_ENGINE" = ardour ] && [ "$HAVE_GOLEM_ENGINE" = 0 ] && WANT_ENGINE=reaper
write_engine_choice "$WANT_ENGINE" || exit 1

# --- 6. Bridge Python (venv + FastAPI/uvicorn/python-osc) -------------------
log "Bridge Python (venv + dépendances)"
"$HERE/bridge-setup.sh"

# LES CAPTURES D'USINE EN ARRIÈRE-PLAN (docs/install-v2.md, lot 4) : si le compte TONE3000 a été connecté sur les
# premières pages de l'installateur (ses jetons sont dans .env), les amplis des sons d'usine se téléchargent PENDANT
# les sons qui suivent (~1 Go). Sans compte : rien, golem les proposera dans Settings ▸ Content ▸ Factory.
CAPTURES_PID=""
if grep -q '^T3K_ACCESS_TOKEN=.' "$HERE/../.env" 2>/dev/null; then
  log "Captures d'usine (TONE3000) — en arrière-plan, pendant les sons"
  rm -f "$HERE/../presets/.factory-fetch.json"
  (cd "$HERE/.." && exec .venv/bin/python -m bridge.factory_fetch) >"$HERE/../presets/.factory-fetch.log" 2>&1 &
  CAPTURES_PID=$!
fi

# --- 6 a. Démos d'usine (~70 Mo) : rendues UNE fois, posées à l'installation (2026-11-15, docs/preset-preview.md §10).
# Jamais fatal : hors ligne, golem les rattrape à son prochain démarrage.
log "Démos d'usine (golem-binaries factory-demos)"
(cd "$HERE/.." && .venv/bin/python -m bridge.factory_demos) || echo "  ⚠ démos d'usine pas téléchargées — golem les rattrapera au démarrage"

# --- 6 bis. Sons lourds (hors Git : captures NAM/IR + piano Salamander) -----
# ~1 Go au total, dont 714 Mo pour le seul Salamander. Rien de tout ça n'entre dans Git : le
# dépôt versionne les RECETTES, ce script récupère le contenu depuis sa source d'origine.
mark phase sounds
if [ "$LIGHT" = 1 ]; then
  log "Sons lourds — SAUTÉS (--light)"
  echo "  → rejoue « ./provision/fetch-assets.sh » quand tu les veux (~1 Go)"
else
  log "Sons : modèles NAM / IR + piano Salamander (~1 Go, patience)"
  "$HERE/fetch-assets.sh"
fi

# les captures lancées plus haut : on les attend ici, en disant où elles en sont (jamais fatal)
if [ -n "$CAPTURES_PID" ]; then
  mark phase captures
  log "Captures d'usine (TONE3000) — fin du téléchargement"
  while kill -0 "$CAPTURES_PID" 2>/dev/null; do
    python3 - "$HERE/../presets/.factory-fetch.json" <<'PYCAP' || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    if d.get("total"):
        print(f"@@progress {d.get('done', 0)} {d['total']}" if __import__("os").environ.get("GOLEM_INSTALLER") == "1" else f"  … {d.get('done', 0)}/{d['total']}")
except Exception:
    pass
PYCAP
    sleep 3
  done
  cap_rc=0; wait "$CAPTURES_PID" || cap_rc=$?
  if [ "$cap_rc" = 0 ]; then echo "  ✓ captures d'usine téléchargées"
  else soft_fail captures "captures d'usine incomplètes — golem les reprend dans Settings ▸ Content ▸ Factory" \
      "Some amp captures could not be downloaded — golem offers them again in Settings ▸ Content ▸ Factory."; fi
fi

# --- 7. Secrets locaux (.env) -----------------------------------------------
log "Fichier .env (clés API)"
if [ ! -f "$HERE/../.env" ]; then
  cp "$HERE/../.env.example" "$HERE/../.env"
  echo "  → .env créé depuis .env.example — colle tes clés (Settings ▸ API, ou édite .env)."
else
  echo "  → .env déjà présent, inchangé."
fi

# le RÉCAPITULATIF : affiché à l'utilisateur (terminal ET journal de l'installateur) → en ANGLAIS et générique
# (CLAUDE.md règle 4 ; il était en français et citait la carte son du mainteneur, 2026-11-03). Une ligne n'apparaît
# que si elle s'applique : Vital absent (même test que plus haut — aucun paquet ne l'installe), --light, terminal seul.
echo
echo "✅ Provisioning complete."
echo "   Left to do:"
# Redémarrer, pas « se déconnecter » : le bridge et REAPER lancés pendant l'install (setsid nohup) survivent à la
# déconnexion, et `golem desktop` les réutiliserait sans les droits temps réel (docs/pitfalls/install.md, 2026-11-03).
# Seulement si CETTE session n'a pas encore le groupe audio : `id -nG` sans argument lit les groupes du processus.
case " $(id -nG 2>/dev/null) " in
  *" audio "*) ;;
  *)
    echo "     • Restart your computer to finish: golem needs real-time audio rights that only apply"
    echo "       after a restart. Without it the audio will crackle."
    ;;
esac
if [ "${GOLEM_INSTALLER:-}" != 1 ]; then
  echo "     • The golem command and the desktop icons: ./provision/install-desktop.sh"
fi
if [ ! -d "$HOME/.vst3/Vital.vst3" ] && [ ! -d "$HOME/.vst3/vitalium.vst3" ] && [ ! -d "$HOME/.lv2/vitalium.lv2" ]; then
  echo "     • Vital is missing: the synth of the Keys lane stays silent. It is free (vital.audio account):"
  echo "       put it in ~/.vst3 — golem finds it at its next start."
fi
if [ "$LIGHT" = 1 ]; then
  echo "     • --light: the sounds were skipped. Amp and piano blocks stay silent until"
  echo "       ./provision/fetch-assets.sh has run."
fi
echo "   Then start golem:  golem desktop   (or golem server, with a tablet as the screen)"
echo "   First start: Settings ▸ Gear ▸ Soundcard adopts your audio interface; Settings ▸ Connect ▸ TONE3000"
echo "   brings the amp captures. Health check: golem doctor"
