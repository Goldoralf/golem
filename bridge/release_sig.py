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
