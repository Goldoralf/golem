# Release signing

> **Status: ACTIVE from v0.6.2 (2026-11-06)** — releases are signed with the maintainer's SSH release key: the tag
> (checked by `git verify-tag`) and a signed file list joined to each release (§5, for everything that installs without
> git). v0.6.2 is the first release that carries the key, so it is the last one installed without verification; every
> later release must be signed. Releases are cut with `tools/release.sh`.
>
> **Key replaced on 2026-11-22** (passphrase of the first key lost): releases from v0.6.5 are signed by `golem release 2`.
> Installs from v0.6.2 to v0.6.4 run the install line once more — §4.1.

## 1. What it protects, and what it does not

A rack updates by checking out a release **tag** (Settings ▸ About, `POST /api/system/update`); a new machine installs
with the README's one-line install (`curl … provision/bootstrap.sh | bash`), which clones the latest release. Both trust GitHub. Signing protects against
a compromised repository — for example a stolen GitHub token that pushes a booby-trapped tag: without the private key the
tag is not signed, and no golem installs it.

It does **not** protect against a compromised host serving the bootstrap (today `raw.githubusercontent.com`): it serves the very script that does the checking.
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

Then put the same line in `GOLEM_RELEASE_SIGNERS` in `provision/bootstrap.sh` (the install line serves it from `main`),
commit, and cut every release with `tools/release.sh vX.Y.Z notes.md` (signed tag, signed file list, checks). The key
lives in the agent (`ssh-add ~/.ssh/golem_release`): the passphrase is never typed into a script. Done on 2026-11-06
with a repository-local signing configuration, not a global one. Because the installed list is the one that
counts, the first release that carries the key is the last one installed without verification; every later release must
be signed.

⚠ Losing the private key means racks that already carry it can no longer use the built-in update (only a manual
`git pull` would). Keep the key backed up, off the rack.

## 4. Rotating the key

First publish a release **signed with the old key** that ADDS the new key to `provision/release-signers` (and to
`GOLEM_RELEASE_SIGNERS`). Once racks have moved to it, a later release removes the old key.

### 4.1 When the old key can no longer sign — done on 2026-11-22

The passphrase of the first release key (`golem release`, 2026-11-06, signed v0.6.2 to v0.6.4) was lost: nothing kept
it but the maintainer's memory, and the desktop keyring held no copy. The rotation above was therefore impossible. What
was done instead:

1. A new key, `golem release 2` (`SHA256:R9hUTiwEkpHeBb3FpOnvM/7M23ijCyC5KJshEb90tos`), signs every release from
   **v0.6.5**. The old private key file is kept aside (`~/.ssh/golem_release.old`) in case the passphrase comes back.
2. `provision/release-signers` carries the new key only.
3. `GOLEM_RELEASE_SIGNERS` in `provision/bootstrap.sh` carries **both** keys while v0.6.4 is still the latest release —
   otherwise the install line would refuse the only release there is. The old line is removed as soon as v0.6.5 is
   "latest".

**What it costs:** a golem installed from v0.6.2 to v0.6.4 verifies with the old key, so its built-in update refuses
v0.6.5 and later ("not signed"). It runs the README's install line once more, over the existing install (Linux: or a
manual `git pull` of the tag); from then on it carries the new key and the button works again. Release notes of v0.6.5
say so first.

**So that it does not happen again:** the passphrase lives in a password manager, and the private key has a copy off
the machine — both checked before the first release signed with a new key.

## 5. The signed file list — installing without git

A GitHub archive cannot be signed: its bytes are not guaranteed to stay the same. So each release also carries
**`SHA256SUMS`** — the SHA-256 of every file of the tag, as `git archive` (and therefore GitHub's zip and tar.gz) ships
it (`tools/release_manifest.py`; 0 differences measured on v0.6.1) — and **`SHA256SUMS.sig`**, its signature with the
tag key (`ssh-keygen -Y sign -n git`). Who checks it:

| Who | How |
|---|---|
| the update by archive (Windows, macOS — [`update.md`](update.md) §3) | `release_update._verify`: `release_sig.verify_manifest` (`ssh-keygen -Y verify`, the **installed** key list), then `release_sig.check_tree` — every file listed, unchanged, and **no file the list does not name**. Before anything is copied. |
| the bootstrap without git (`provision/bootstrap.sh`, `verify_archive`) | same checks with `ssh-keygen`, `sha256sum -c` and a file-list comparison; on any difference the download is erased and the install stops |
| the bootstrap and the update **with** git | `git verify-tag` (§2) |

**Not covered:** the Windows bootstrap (`provision/bootstrap.ps1`) checks no signature yet — it downloads the archive
as before. Once installed, a Windows golem's updates are checked (by the bridge, which needs `ssh-keygen.exe`, part of
Windows' OpenSSH client).
