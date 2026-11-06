# SPDX-License-Identifier: GPL-3.0-or-later
"""La signature des releases (docs/release-signing.md) : sans clé déclarée, rien ne change ; avec une clé, seul un tag
qu'elle a signé passe — et c'est la liste de la version INSTALLÉE qui fait foi."""
import shutil
import subprocess

import pytest

from bridge import release_sig

pytestmark = pytest.mark.skipif(not (shutil.which("git") and shutil.which("ssh-keygen")), reason="git/ssh-keygen absents")


def _git(root, *a):
    subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                   capture_output=True, text=True, check=True)


@pytest.fixture
def repo(tmp_path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "key")], check=True)
    root = tmp_path / "golem"
    (root / "provision").mkdir(parents=True)
    (root / "provision" / "release-signers").write_text("# vide\n")
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "x")
    _git(root, "-c", "gpg.format=ssh", "-c", f"user.signingkey={tmp_path / 'key'}", "tag", "-s", "v1", "-m", "v1")
    _git(root, "tag", "-a", "v2", "-m", "v2")
    pub = (tmp_path / "key.pub").read_text().strip()
    return root, f'golem namespaces="git" {pub}\n'


def test_sans_cle_declaree_rien_n_est_verifie(repo):
    root, _ = repo
    assert release_sig.verify("v1", root=str(root))[0] is None
    assert release_sig.verify("v2", root=str(root))[0] is None


def test_avec_une_cle_seul_le_tag_signe_passe(repo):
    root, line = repo
    (root / "provision" / "release-signers").write_text("# clé\n" + line)
    assert release_sig.verify("v1", root=str(root))[0] is True
    ok, why = release_sig.verify("v2", root=str(root))
    assert ok is False and "not signed" in why
