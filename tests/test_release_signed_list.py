# SPDX-License-Identifier: GPL-3.0-or-later
"""La liste signée d'une release (docs/release-signing.md §5, 2026-11-06) : ce qui s'installe SANS git — la mise à jour
par archive (Windows, macOS) et le bootstrap — vérifie SHA256SUMS signé par la clé des tags, puis chaque fichier. Avec
une vraie clé ed25519 de test (ssh-keygen), sans phrase de passe."""
import hashlib
import os
import shutil
import subprocess

import pytest

from bridge import config as C
from bridge import release_sig as S

pytestmark = pytest.mark.skipif(not shutil.which("ssh-keygen") or os.name == "nt", reason="ssh-keygen needed")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _key(tmp_path, name="k"):
    k = tmp_path / name
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "test", "-f", str(k)], check=True)
    return k


def _signers(root, key):
    (root / "provision").mkdir(parents=True, exist_ok=True)
    line = f'golem namespaces="git" {(key.with_suffix(".pub")).read_text().strip()}\n'
    (root / "provision" / "release-signers").write_text("# clés\n" + line)
    return line


def _tree(d, files):
    for rel, txt in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt)


def _sums(d):
    lines = []
    for base, _dirs, files in os.walk(d):
        for fn in files:
            p = os.path.join(base, fn)
            rel = os.path.relpath(p, d).replace(os.sep, "/")
            lines.append(f"{hashlib.sha256(open(p, 'rb').read()).hexdigest()}  {rel}")
    return ("\n".join(sorted(lines, key=lambda ln: ln.split('  ', 1)[1])) + "\n").encode()


def _sign(key, sums, tmp_path):
    f = tmp_path / "SHA256SUMS"
    f.write_bytes(sums)
    subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key), "-n", "git", str(f)], check=True, capture_output=True)
    return (tmp_path / "SHA256SUMS.sig").read_bytes()


@pytest.fixture
def release(tmp_path, monkeypatch):
    root = tmp_path / "install"
    key = _key(tmp_path)
    line = _signers(root, key)
    monkeypatch.setattr(C, "ROOT", str(root))
    src = tmp_path / "golem-0.6.2"
    _tree(src, {"bridge/app.py": "v2", "provision/x.sh": "echo", "a b/space.txt": "x"})
    sums = _sums(src)
    return {"root": root, "key": key, "line": line, "src": src, "sums": sums, "sig": _sign(key, sums, tmp_path),
            "tmp": tmp_path}


def test_une_liste_signee_par_la_cle_declaree_passe(release):
    assert S.verify_manifest(release["sums"], release["sig"])[0] is True
    assert S.check_tree(str(release["src"]), release["sums"].decode()) == []


def test_une_autre_cle_ou_une_liste_retouchee_est_refusee(release):
    other = _key(release["tmp"], "other")
    (release["tmp"] / "o").mkdir()
    forged = _sign(other, release["sums"], release["tmp"] / "o")
    assert S.verify_manifest(release["sums"], forged)[0] is False
    assert S.verify_manifest(release["sums"].replace(b"bridge/app.py", b"bridge/evil.py"), release["sig"])[0] is False


def test_un_fichier_change_manquant_ou_en_plus_est_refuse(release):
    src, sums = release["src"], release["sums"].decode()
    (src / "bridge" / "app.py").write_text("tampered")
    (src / "sitecustomize.py").write_text("import os")
    os.remove(src / "provision" / "x.sh")
    bad = S.check_tree(str(src), sums)
    assert "changed: bridge/app.py" in bad and "not in the signed list: sitecustomize.py" in bad
    assert "missing: provision/x.sh" in bad


def test_sans_cle_declaree_rien_n_est_verifie(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "ROOT", str(tmp_path))
    assert S.verify_manifest(b"", b"")[0] is None and not S.declared()


def test_la_mise_a_jour_par_archive_verifie_avant_de_copier(release, monkeypatch):
    from bridge import release_update as U
    root = release["root"]
    _tree(root, {"bridge/app.py": "v1", "bridge/requirements.lock": "a"})
    calls = []
    monkeypatch.setattr(U, "write_installed", lambda *a: calls.append("written"))
    ok = lambda tag: (release["sums"], release["sig"])
    U.apply("v0.6.2", fetch_src=lambda tag, w: str(release["src"]), fetch_signed=ok)
    assert (root / "bridge" / "app.py").read_text() == "v2" and calls == ["written"]
    # une archive retouchée : refusée AVANT toute copie
    (release["src"] / "bridge" / "app.py").write_text("evil")
    (root / "bridge" / "app.py").write_text("v2")
    with pytest.raises(RuntimeError, match="does not match its signed list"):
        U.apply("v0.6.2", fetch_src=lambda tag, w: str(release["src"]), fetch_signed=ok)
    assert (root / "bridge" / "app.py").read_text() == "v2"
    # pas de liste jointe à la release : refusée
    def none(tag):
        raise OSError("404")
    with pytest.raises(RuntimeError, match="no signed file list"):
        U.apply("v0.6.2", fetch_src=lambda tag, w: str(release["src"]), fetch_signed=none)


def _bootstrap_verify(release, mutate=None):
    """La fonction verify_archive de provision/bootstrap.sh, sous dash (curl | sh), sur un « GitHub » file://."""
    rel = release["tmp"] / "repo" / "releases" / "download" / "v0.6.2"
    rel.mkdir(parents=True)
    (rel / "SHA256SUMS").write_bytes(release["sums"])
    (rel / "SHA256SUMS.sig").write_bytes(release["sig"])
    src = release["tmp"] / "cache" / "golem-v0.6.2"
    shutil.copytree(release["src"], src)
    if mutate:
        mutate(src)
    script = open(os.path.join(ROOT, "provision", "bootstrap.sh"), encoding="utf-8").read()
    a, b = script.index("say() {"), script.index("# ── 1. le strict minimum")
    body = script[a:b] + 'verify_archive\n'
    env = dict(os.environ, SRC=str(src), REF="v0.6.2", REPO="file://" + str(release["tmp"] / "repo"),
               GOLEM_RELEASE_SIGNERS=release["line"].strip())
    shell = shutil.which("dash") or "sh"
    r = subprocess.run([shell, "-c", 'SRC="$SRC"; REF="$REF"; REPO="$REPO"; GOLEM_RELEASE_SIGNERS="$GOLEM_RELEASE_SIGNERS"\n'
                        + body], env=env, capture_output=True, text=True)
    return r, src


def test_le_bootstrap_sans_git_verifie_la_liste_signee(release):
    r, src = _bootstrap_verify(release)
    assert r.returncode == 0 and "signed file list verified" in r.stdout
    assert src.is_dir()


def test_le_bootstrap_refuse_un_fichier_ajoute_et_efface_tout(release):
    r, src = _bootstrap_verify(release, mutate=lambda d: (d / "evil.sh").write_text("rm -rf ~"))
    assert r.returncode != 0 and "files its signed list does not name" in r.stderr
    assert not src.exists()
