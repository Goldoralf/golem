#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# GoleM — le bootstrap en une ligne (docs/installer.md §2) :
#     curl -fsSL https://get.golem.fm | sh          (ou : bash provision/bootstrap.sh)
# Il ne fait QUE trois choses, sans sudo : vérifier le strict minimum (Ubuntu 24.04, x86_64, python3,
# curl), récupérer le dépôt à la DERNIÈRE RELEASE dans un cache, et lancer l'installateur graphique
# (installer/server.py, bibliothèque standard) qui pose les questions et exécute provision/install.sh.
# Variables : GOLEM_REF (tag, défaut = dernière release) · GOLEM_REPO (défaut GitHub) · GOLEM_INSTALLER_DRY=1
# POSIX : `curl … | sh` le lance avec dash, qui ne connaît pas pipefail (« Illegal option -o pipefail », le script
# mourait à la ligne 9 sur toute Ubuntu — trouvé au premier test en VM, 2026-10-15). On le garde là où il existe.
set -eu
# shellcheck disable=SC3040
(set -o pipefail) 2>/dev/null && set -o pipefail
REPO="${GOLEM_REPO:-https://github.com/Goldoralf/golem}"
# CLÉ(S) DE RELEASE (docs/release-signing.md) — au format de provision/release-signers. Vide = pas de vérification
# (le comportement d'avant). Renseignée : la release clonée doit être un tag SIGNÉ par cette clé, sinon on s'arrête.
# Elle vit ICI, dans le script servi par get.golem.fm, et pas dans le dépôt téléchargé : une release piégée ne
# choisit pas la clé qui la vérifie.
GOLEM_RELEASE_SIGNERS=""
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/golem-installer"
say() { printf '\033[1;36m▶ %s\033[0m\n' "$*"; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# SANS GIT, LA LISTE SIGNÉE DE LA RELEASE (docs/release-signing.md §5, 2026-11-06) : une archive GitHub ne se signe pas.
# La release joint SHA256SUMS (l'empreinte de chaque fichier du tag) et SHA256SUMS.sig ; on vérifie la signature avec la
# clé ci-dessus, puis chaque fichier extrait — et aucun fichier en plus. ssh-keygen et sha256sum sont dans une Ubuntu de
# base (openssh-client, coreutils). Tout écart : on efface et on s'arrête.
verify_archive() {
  bad() { rm -rf "$SRC" "$SRC.signers" "$SRC.sums" "$SRC.sums.sig" "$SRC.have" "$SRC.want"; die "$1"; }
  command -v ssh-keygen >/dev/null 2>&1 || bad "ssh-keygen is needed to check the release signature (sudo apt install openssh-client)."
  printf '%s\n' "$GOLEM_RELEASE_SIGNERS" > "$SRC.signers"
  curl -fsSL "$REPO/releases/download/$REF/SHA256SUMS" -o "$SRC.sums" \
    && curl -fsSL "$REPO/releases/download/$REF/SHA256SUMS.sig" -o "$SRC.sums.sig" \
    || bad "release $REF has no signed file list — not installing it."
  ssh-keygen -Y verify -f "$SRC.signers" -I golem -n git -s "$SRC.sums.sig" < "$SRC.sums" >/dev/null 2>&1 \
    || bad "release $REF is NOT signed by the golem release key — not installing it."
  (cd "$SRC" && sha256sum -c --quiet --strict "$SRC.sums") >/dev/null 2>&1 \
    || bad "the downloaded files of $REF do not match its signed list — not installing it."
  (cd "$SRC" && find . -type f | sed 's#^\./##' | LC_ALL=C sort) > "$SRC.have"
  cut -c67- "$SRC.sums" | LC_ALL=C sort > "$SRC.want"
  cmp -s "$SRC.have" "$SRC.want" || bad "the download of $REF holds files its signed list does not name — not installing it."
  rm -f "$SRC.signers" "$SRC.sums" "$SRC.sums.sig" "$SRC.have" "$SRC.want"
  say "release $REF: signed file list verified"
}

# ── 1. le strict minimum (le reste est vérifié À L'ÉCRAN, avec des phrases) ──
. /etc/os-release 2>/dev/null || true
# les systèmes testés : installer/platform_linux.py TESTED (le même texte à l'écran)
case "${ID:-}:${VERSION_ID:-}" in
  ubuntu:24.04*|ubuntu:26.04*|debian:13*|linuxmint:22*) ;;
  *) say "⚠ golem is tested on Ubuntu 24.04 and 26.04, Debian 13 and Linux Mint 22 — you have ${PRETTY_NAME:-an unknown system}; the installer will tell you what breaks." ;;
esac
[ "$(uname -m)" = x86_64 ] || die "golem needs a 64-bit x86 machine (Reaper and the neural plugins ship for x86_64 only)."
command -v python3 >/dev/null 2>&1 || die "python3 is missing (it ships with Ubuntu — sudo apt install python3)."
# curl ne sert qu'à TÉLÉCHARGER le dépôt : depuis un clone (GOLEM_SRC, ./install-linux.sh) on n'en a pas besoin, et une
# Ubuntu Desktop vierge ne l'a pas — il arrive avec packages.txt (2026-11-03)
if [ -z "${GOLEM_SRC:-}" ] || [ ! -d "$GOLEM_SRC/provision" ]; then
  command -v curl >/dev/null 2>&1 || die "curl is missing (sudo apt install curl)."
fi

# ── 2. le dépôt à la dernière release (archive, pas besoin de git ; git arrive avec les paquets) ──
if [ -n "${GOLEM_SRC:-}" ] && [ -d "$GOLEM_SRC/provision" ]; then
  SRC="$GOLEM_SRC"; say "using $SRC"
else
  REF="${GOLEM_REF:-}"
  if [ -z "$REF" ]; then
    REF=$(curl -fsSL "https://api.github.com/repos/${REPO#https://github.com/}/releases/latest" 2>/dev/null | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p' | head -1 || true)
    # le PLUS RÉCENT par numéro de version (sort -V), pas le premier que l'API rend : v2.10.0 passe après v2.9.0
    [ -n "$REF" ] || REF=$(curl -fsSL "https://api.github.com/repos/${REPO#https://github.com/}/tags" 2>/dev/null | sed -n 's/.*"name": *"\(v[0-9][^"]*\)".*/\1/p' | sort -rV | head -1 || true)
    [ -n "$REF" ] || REF=main
  fi
  say "golem $REF"
  mkdir -p "$CACHE"; SRC="$CACHE/golem-$REF"
  if [ -n "$GOLEM_RELEASE_SIGNERS" ]; then
    # une branche ne se signe pas ; avec git on vérifie le TAG, sans git la LISTE SIGNÉE de la release (verify_archive)
    [ "$REF" != main ] || die "no signed release found — refusing to install an unverified branch."
    rm -rf "$SRC"                                        # jamais un cache qu'on n'a pas vérifié nous-mêmes
  fi
  if [ ! -d "$SRC/provision" ]; then
    rm -rf "$SRC"; mkdir -p "$SRC"
    if command -v git >/dev/null 2>&1; then
      git clone --quiet --depth 1 --branch "$REF" "$REPO.git" "$SRC" || die "clone failed ($REPO @ $REF)"
      if [ -n "$GOLEM_RELEASE_SIGNERS" ]; then
        printf '%s\n' "$GOLEM_RELEASE_SIGNERS" > "$SRC.signers"
        git -C "$SRC" fetch --quiet --depth 1 origin "refs/tags/$REF:refs/tags/$REF" 2>/dev/null || true
        if git -C "$SRC" -c gpg.format=ssh -c gpg.ssh.allowedSignersFile="$SRC.signers" verify-tag "$REF" >/dev/null 2>&1; then
          rm -f "$SRC.signers"; say "release $REF: signature verified"
        else
          rm -rf "$SRC" "$SRC.signers"; die "release $REF is NOT signed by the golem release key — not installing it."
        fi
      fi
    else
      curl -fsSL "$REPO/archive/refs/tags/$REF.tar.gz" -o "$SRC.tgz" 2>/dev/null || curl -fsSL "$REPO/archive/refs/heads/$REF.tar.gz" -o "$SRC.tgz" || die "download failed ($REPO @ $REF)"
      tar -xzf "$SRC.tgz" -C "$SRC" --strip-components=1 && rm -f "$SRC.tgz"
      [ -z "$GOLEM_RELEASE_SIGNERS" ] || verify_archive
    fi
  fi
fi

# reçu d'install (docs/uninstall.md §2) : le cache de l'installateur est à nous. Une release d'avant le reçu
# n'a pas receipt.py : l'appel échoue en silence, comme tout appel au reçu (jamais fatal).
if [ "$SRC" = "$CACHE/golem-${REF:-}" ]; then
  python3 "$SRC/provision/receipt.py" add "$CACHE" --kind dir --by provision/bootstrap.sh --group golem >/dev/null 2>&1 || true
fi

# ── 3. l'installateur graphique ──
say "opening the installer in your browser"
# GOLEM_INSTALLER_PORT fixe le port (VM sans bureau : un tunnel ssh -L l'atteint depuis la machine hôte)
exec python3 "$SRC/installer/server.py" --src "$SRC" --open ${GOLEM_INSTALLER_DRY:+--dry} ${GOLEM_INSTALLER_PORT:+--port "$GOLEM_INSTALLER_PORT"}
