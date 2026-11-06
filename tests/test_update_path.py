# SPDX-License-Identifier: GPL-3.0-or-later
"""La mise à jour depuis System ▸ About, sur de VRAIS dépôts git temporaires (2026-11-06) : une install venue d'une archive
devient un dépôt (installer.platform_linux.ensure_git_repo), la release suivante se voit avec ses notes en anglais (le
message du tag annoté, sans signature), la bascule se fait, et reload.sh sait qu'il doit relancer REAPER."""
import asyncio
import os
import shutil
import subprocess

import pytest

pytestmark = pytest.mark.skipif(not shutil.which("git") or os.name == "nt", reason="git and bash needed")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _git(cwd, *a):
    return subprocess.run(["git", "-C", str(cwd), "-c", "user.name=t", "-c", "user.email=t@t", *a],
                          capture_output=True, text=True, check=True).stdout.strip()


@pytest.fixture
def remote(tmp_path):
    """Un « GitHub » local : v1, puis v2 (reaper/ change) avec des notes et un faux bloc de signature."""
    work = tmp_path / "work"
    (work / "reaper").mkdir(parents=True)
    (work / "presets").mkdir()
    (work / "presets" / ".keep").write_text("")
    (work / "reaper" / "a.lua").write_text("-- v1\n")
    (work / "README.md").write_text("v1\n")
    _git(tmp_path, "-c", "init.defaultBranch=main", "init", "-q", str(work))
    _git(work, "add", "-A")
    _git(work, "commit", "-q", "-m", "un message de commit en français")
    _git(work, "tag", "-a", "v1", "-m", "golem v1")
    (work / "reaper" / "a.lua").write_text("-- v2\n")
    _git(work, "commit", "-q", "-am", "encore du français")
    _git(work, "tag", "-a", "v2", "-m", "What's new\n\n- one\n- two\n-----BEGIN SSH SIGNATURE-----\nxx\n")
    bare = tmp_path / "remote.git"
    _git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    return bare


class Ctx:
    S = {"dry": False}

    def __init__(self):
        self.logs = []

    def run(self, cmd, step, cwd=None, extra_env=None):
        return subprocess.run(cmd, cwd=cwd, capture_output=True).returncode

    def log(self, line, step=None):
        self.logs.append(line)


def test_archive_puis_mise_a_jour_puis_reaper(tmp_path, remote, monkeypatch):
    from installer import platform_linux as L
    from bridge import config as C, routes_system as R
    monkeypatch.setattr(L, "DEFAULT_REPO", "file://" + str(remote))
    # 1. l'archive de v1, extraite comme le fait le bootstrap sans git, dans golem-<tag>
    t = tmp_path / "golem-v1"
    t.mkdir()
    arc = subprocess.run(["git", "-C", str(remote), "archive", "v1"], capture_output=True, check=True).stdout
    subprocess.run(["tar", "-x", "-C", str(t)], input=arc, check=True)
    assert not (t / ".git").exists()
    ctx = Ctx()
    L.ensure_git_repo(ctx, str(t), str(t))
    assert _git(t, "describe", "--tags") == "v1"
    assert _git(t, "status", "--porcelain", "--untracked-files=no") == ""
    assert any("linked to the golem repository at v1" in m for m in ctx.logs)
    # 2. la page About voit v2, avec SES notes (pas les sujets de commit, pas la signature)
    monkeypatch.setattr(C, "ROOT", str(t))
    st = R.system_update(fetch=1)
    assert (st["status"], st["latest"], st["clean"]) == ("update-available", "v2", True)
    assert st["notes"] == "What's new\n\n- one\n- two"
    # 3. la bascule (la relance du bridge est interceptée)
    real = subprocess.Popen
    spawned = []

    def popen(args, *a, **k):
        if args and args[0] == "bash" and "reload.sh" in " ".join(args):
            spawned.append(args)
            return None
        return real(args, *a, **k)
    monkeypatch.setattr(subprocess, "Popen", popen)
    r = asyncio.run(R.system_update_apply({"tag": "v2"}))
    assert r["ok"] and spawned and _git(t, "describe", "--tags") == "v2"
    assert R.system_update(fetch=0)["status"] == "up-to-date"
    # 4. reload.sh : REAPER a été lancé sur v1 (empreinte notée) -> ses scripts ont changé, il sera relancé
    lib = os.path.join(ROOT, "provision", "lib-reaper.sh")
    sh = lambda body: subprocess.run(["bash", "-c", f'. "{lib}"; {body}'], cwd=str(t)).returncode
    _git(t, "checkout", "-q", "v1")
    assert sh('record_reaper_tree "$PWD"') == 0
    assert sh('reaper_scripts_stale "$PWD"') == 1          # même commit : REAPER laissé
    _git(t, "checkout", "-q", "v2")
    assert sh('reaper_scripts_stale "$PWD"') == 0          # reaper/ a changé : REAPER relancé


def test_un_tag_leger_n_a_pas_de_notes(tmp_path, remote, monkeypatch):
    from bridge import config as C, routes_system as R
    t = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", str(remote), str(t))
    _git(t, "tag", "light")
    monkeypatch.setattr(C, "ROOT", str(t))
    assert R._tag_notes("light") == "" and R._tag_notes(None) == ""
    assert R._tag_notes("v1") == "golem v1"


def test_sans_nom_de_release_rien_n_est_converti(tmp_path):
    from installer import platform_linux as L
    t = tmp_path / "golem"                                   # pas « golem-<tag> » : on ne devine pas
    t.mkdir()
    ctx = Ctx()
    L.ensure_git_repo(ctx, str(t), str(t))
    assert not (t / ".git").exists() and ctx.logs
