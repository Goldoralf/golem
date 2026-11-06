# Release signing

> **Status: CODED, INACTIVE until a key is declared** — verification of signed release tags by the built-in update and by
> the bootstrap installer; it does nothing while no release key is listed.

## 1. What it protects, and what it does not

A rack updates by checking out a release **tag** (Settings ▸ About, `POST /api/system/update`); a new machine installs
with `curl -fsSL https://get.golem.fm | sh`, which clones the latest release. Both trust GitHub. Signing protects against
a compromised repository — for example a stolen GitHub token that pushes a booby-trapped tag: without the private key the
tag is not signed, and no golem installs it.

It does **not** protect against a compromised `get.golem.fm`: that host serves the very script that does the checking.
This is the limit of any `curl | sh`, and the reason the bootstrap's key list lives in the script, not in the repository.

## 2. Where the keys live

| Who verifies | Key list | Why there |
|---|---|---|
| the built-in update | `provision/release-signers` **of the installed version** (`bridge/release_sig.py`, `verify`) | a release must not choose who verifies it |
| the bootstrap | `GOLEM_RELEASE_SIGNERS` in `provision/bootstrap.sh` | the downloaded repository is not trusted yet |

Both use git's SSH "allowed signers" format (`<name> namespaces="git" ssh-ed25519 AAAA…`); blank lines and `#` comments
are ignored. `verify` copies the installed list to a temporary file **before** the checkout and runs
`git -c gpg.format=ssh -c gpg.ssh.allowedSignersFile=<copy> verify-tag <tag>`.

**Empty list = no verification** (the update proceeds as an unsigned install, and says so). Behaviour per entry point:

- `GET /api/system/update` returns `signed` for the latest tag: `true` (signed by a declared key), `false` (will be
  refused — also returned when the check itself fails, e.g. `ssh-keygen` missing), `null` (no key declared, or no tag).
- `POST /api/system/update` refuses with **409** and the reason when `verify` returns `false`; otherwise it checks out the
  tag and returns `signed` in its reply (`bridge/routes_system.py`, `system_update_apply`).
- `provision/bootstrap.sh`, when `GOLEM_RELEASE_SIGNERS` is set: requires `git`, refuses to install a branch (`main`)
  instead of a tag, never reuses an unverified cache, fetches the tag and runs `verify-tag`; an unsigned tag aborts the
  install ("release … is NOT signed by the golem release key").

## 3. Activating it (once, by the maintainer who holds the key)

```sh
ssh-keygen -t ed25519 -C "golem release" -f ~/.ssh/golem_release        # use a passphrase
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/golem_release.pub
echo "golem namespaces=\"git\" $(cat ~/.ssh/golem_release.pub)" >> provision/release-signers
```

Then put the same line in `GOLEM_RELEASE_SIGNERS` in `provision/bootstrap.sh` (and publish that script on
get.golem.fm), commit, and **sign every tag**: `git tag -s vX.Y.Z -m vX.Y.Z`. Because the installed list is the one that
counts, the first release that carries the key is the last one installed without verification; every later release must
be signed.

⚠ Losing the private key means racks that already carry it can no longer use the built-in update (only a manual
`git pull` would). Keep the key backed up, off the rack.

## 4. Rotating the key

First publish a release **signed with the old key** that ADDS the new key to `provision/release-signers` (and to
`GOLEM_RELEASE_SIGNERS`). Once racks have moved to it, a later release removes the old key.
