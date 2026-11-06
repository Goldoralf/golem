# SPDX-License-Identifier: GPL-3.0-or-later
"""La signature des releases (docs/release-signing.md, audit 2026-10-15).

Un tag de release peut être signé (git tag -s, clé SSH). `provision/release-signers` liste les clés autorisées ; la
liste lue est celle de la version INSTALLÉE, avant la bascule — une release piégée ne choisit pas qui la vérifie.
Aucune clé déclarée = aucune vérification (le comportement historique), et c'est dit."""
import os
import shutil
import subprocess
import tempfile

from . import config as C

SIGNERS = os.path.join("provision", "release-signers")


def _keys(path):
    try:
        with open(path, encoding="utf-8") as f:
            return [ln for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
    except OSError:
        return []


def verify(tag, root=None):
    """(True, why) signé par une clé déclarée · (False, why) refusé · (None, why) aucune clé déclarée."""
    root = root or C.ROOT
    signers = os.path.join(root, SIGNERS)
    if not _keys(signers):
        return None, "no release key declared (provision/release-signers) — the release is not verified"
    if not shutil.which("ssh-keygen"):
        return False, "ssh-keygen is missing — cannot check the release signature"
    fd, copy = tempfile.mkstemp(prefix="golem-signers-")       # la liste d'AVANT la bascule, hors du dépôt
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out, open(signers, encoding="utf-8") as src:
            out.write(src.read())
        r = subprocess.run(["git", "-C", root, "-c", "gpg.format=ssh", "-c", f"gpg.ssh.allowedSignersFile={copy}",
                            "verify-tag", tag], capture_output=True, text=True, timeout=30)
    finally:
        os.unlink(copy)
    if r.returncode == 0:
        return True, "signed by a declared release key"
    return False, f"release {tag} is not signed by a declared key — refusing to install it"


# ── LA LISTE SIGNÉE D'UNE RELEASE (2026-11-06) — pour ce qui s'installe SANS git ─────────────────────────────────────
# Une archive GitHub ne se signe pas (ses octets ne sont pas garantis stables) : chaque release publie SHA256SUMS, les
# empreintes de TOUS les fichiers du tag (tools/release_manifest.py), et SHA256SUMS.sig, sa signature
# (`ssh-keygen -Y sign -n git`, la clé des tags). La mise à jour par archive (bridge/release_update.py) et le bootstrap
# sans git vérifient la signature, puis chaque fichier extrait — et refusent un fichier que la liste ne nomme pas.
PRINCIPAL = "golem"            # le nom des lignes de provision/release-signers
NAMESPACE = "git"              # celui que ces lignes autorisent (namespaces="git")


def declared(root=None):
    return bool(_keys(os.path.join(root or C.ROOT, SIGNERS)))


def verify_manifest(sums, sig, root=None):
    """(True, why) · (False, why) · (None, why) aucune clé déclarée — la signature de SHA256SUMS (octets)."""
    root = root or C.ROOT
    signers = os.path.join(root, SIGNERS)
    if not _keys(signers):
        return None, "no release key declared (provision/release-signers) — the release is not verified"
    if not shutil.which("ssh-keygen"):
        return False, "ssh-keygen is missing — cannot check the release signature"
    tmp = tempfile.mkdtemp(prefix="golem-sig-")
    try:
        allowed, sigf = os.path.join(tmp, "signers"), os.path.join(tmp, "SHA256SUMS.sig")
        shutil.copyfile(signers, allowed)                  # la liste d'AVANT la bascule
        with open(sigf, "wb") as f:
            f.write(sig)
        r = subprocess.run(["ssh-keygen", "-Y", "verify", "-f", allowed, "-I", PRINCIPAL, "-n", NAMESPACE, "-s", sigf],
                           input=sums, capture_output=True, timeout=30)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if r.returncode == 0:
        return True, "signed by a declared release key"
    return False, "the release file list is not signed by a declared key — refusing to install it"


def check_tree(src, sums):
    """Ce qui cloche entre un dossier extrait et SHA256SUMS (texte « <sha256>  <chemin> ») : [] = conforme."""
    import hashlib
    want = {}
    for ln in sums.splitlines():
        if ln.strip():
            h, _, rel = ln.partition("  ")
            want[rel.strip()] = h.strip()
    have = set()
    for base, dirs, files in os.walk(src):
        for fn in files:
            have.add(os.path.relpath(os.path.join(base, fn), src).replace(os.sep, "/"))
    bad = [f"not in the signed list: {p}" for p in sorted(have - set(want))]
    bad += [f"missing: {p}" for p in sorted(set(want) - have)]
    for rel in sorted(have & set(want)):
        with open(os.path.join(src, *rel.split("/")), "rb") as f:
            if hashlib.sha256(f.read()).hexdigest() != want[rel]:
                bad.append(f"changed: {rel}")
    return bad
