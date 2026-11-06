#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# SORTIR UNE RELEASE de golem (docs/update.md §5, docs/release-signing.md §5), toujours de la même façon :
#     tools/release.sh v0.6.2 notes.md
# notes.md : les notes EN ANGLAIS (l'écran de mise à jour les montre). Le script refuse si l'arbre n'est pas propre, si
# HEAD n'est pas origin/main, si la CI de HEAD n'est pas verte ou si le crible du dépôt public trouve quelque chose.
# Puis : tag annoté SIGNÉ (clé SSH de release, dans l'agent), push du tag, SHA256SUMS + SHA256SUMS.sig, release GitHub
# « Latest » avec ces deux fichiers, et vérification de ce qui est publié.
set -euo pipefail
TAG="${1:?usage: tools/release.sh vX.Y.Z notes.md}"
NOTES="${2:?usage: tools/release.sh vX.Y.Z notes.md}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
KEY="${GOLEM_RELEASE_KEY:-$HOME/.ssh/golem_release.pub}"
REPO_SLUG="${GOLEM_REPO_SLUG:-Goldoralf/golem}"
die() { echo "✗ $*" >&2; exit 1; }

[[ "$TAG" =~ ^v[0-9]+(\.[0-9]+)+$ ]] || die "$TAG is not a version tag (vX.Y.Z)"
[ -s "$NOTES" ] || die "no notes in $NOTES"
[ -f "$KEY" ] || die "release key not found: $KEY"
ssh-add -L 2>/dev/null | grep -qF "$(cut -d' ' -f2 "$KEY")" || die "the release key is not in the agent — ssh-add ${KEY%.pub}"
grep -qF "$(cut -d' ' -f2 "$KEY")" provision/release-signers || die "the key is not in provision/release-signers"
[ -z "$(git status --porcelain --untracked-files=no)" ] || die "the tree has uncommitted changes"
git fetch -q origin
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || die "HEAD is not origin/main — push first"
git rev-parse -q --verify "refs/tags/$TAG" >/dev/null && die "$TAG already exists — never move a published tag"
HEAD=$(git rev-parse HEAD)
ci=$(gh run list -R "$REPO_SLUG" -L 20 --json headSha,name,conclusion \
       -q ".[] | select(.headSha==\"$HEAD\") | select(.name==\"CI\") | .conclusion" | head -1)
[ "$ci" = success ] || die "CI of $HEAD is '${ci:-not found}', not success"
python3 tools/public_export.py --deny ~/golem-public/denylist.txt --allow ~/golem-public/allowlist.txt --summary 2>&1 \
  | tail -1 | grep -q ' 0 forbidden' || die "the public scan finds forbidden words"

echo "→ signed tag $TAG on $(git rev-parse --short HEAD)"
git -c gpg.format=ssh -c user.signingkey="$KEY" tag -s "$TAG" -F "$NOTES"
git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile=provision/release-signers verify-tag "$TAG" >/dev/null 2>&1 \
  || die "the new tag does not verify against provision/release-signers"
git push -q origin "$TAG"

OUT=$(mktemp -d)
python3 tools/release_manifest.py "$TAG" --out "$OUT"
ssh-keygen -Y sign -f "$KEY" -n git "$OUT/SHA256SUMS" >/dev/null 2>&1 || die "signing SHA256SUMS failed"
ssh-keygen -Y verify -f provision/release-signers -I golem -n git -s "$OUT/SHA256SUMS.sig" < "$OUT/SHA256SUMS" >/dev/null \
  || die "SHA256SUMS.sig does not verify"

echo "→ GitHub release $TAG (Latest)"
gh release create "$TAG" -R "$REPO_SLUG" --title "golem $TAG" --notes-file "$NOTES" --latest --verify-tag \
  "$OUT/SHA256SUMS" "$OUT/SHA256SUMS.sig"
rm -rf "$OUT"
latest=$(curl -fsSL "https://api.github.com/repos/$REPO_SLUG/releases/latest" | sed -n 's/.*"tag_name": *"\([^"]*\)".*/\1/p')
[ "$latest" = "$TAG" ] || die "releases/latest says $latest, not $TAG"
echo "✓ $TAG published, signed, with its signed file list — releases/latest = $TAG"
