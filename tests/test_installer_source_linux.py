# SPDX-License-Identifier: GPL-3.0-or-later
"""L'ÉTAPE « source » DE L'INSTALLATEUR LINUX SUR UNE INSTALL EXISTANTE (2026-11-22).

Relancer la ligne d'installation par-dessus un golem doit le passer à la release de l'installateur. Ce n'était pas le
cas : `git pull --ff-only` s'arrêtait sur une install figée sur un tag (HEAD détachée) — exactement ce que pose la
ligne d'installation. Rejoué sur une install v0.6.4 → v0.7.0 : rc=1, l'install restait en v0.6.4.

De VRAIS dépôts git, fabriqués comme le font provision/bootstrap.sh (clone de profondeur 1 sur le tag), l'installateur
(`git clone` du cache) et ensure_git_repo (install venue d'une archive)."""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

pytestmark = pytest.mark.skipif(not sys.platform.startswith("linux") or not shutil.which("git"),
                                reason="the Linux installer's source step, on real git repositories")

ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t",
           GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)


def git(cwd, *args):
    r = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=ENV)
    assert r.returncode == 0, f"git {' '.join(args)}: {r.stderr}"
    return r.stdout.strip()


class Ctx:
    """Le contexte de l'installateur, réduit à ce que l'étape appelle : un journal et des commandes réelles."""

    def __init__(self):
        self.S, self.lines = {"dry": False}, []

    def log(self, line, step=None):
        self.lines.append(str(line))

    def run(self, cmd, step, cwd=None, extra_env=None):
        r = subprocess.run(cmd, capture_output=True, text=True, env=ENV, cwd=cwd)
        self.lines += (r.stdout + r.stderr).splitlines()
        return r.returncode


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Un « GitHub » local à deux releases (v1, v2), et de quoi fabriquer les caches du bootstrap."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_SYSTEM", os.devnull)
    for k in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(k, ENV[k])
    up = tmp_path / "upstream"
    up.mkdir()
    git(up, "-c", "init.defaultBranch=main", "init", "-q")
    (up / "provision").mkdir()
    (up / ".gitignore").write_text("presets/\nconfig/io.json\n")
    for n in (1, 2):
        (up / "provision" / "version.txt").write_text(f"v{n}\n")
        (up / "code.py").write_text(f"VERSION = {n}\n")
        git(up, "add", "-A")
        git(up, "commit", "-q", "-m", f"release {n}")
        git(up, "tag", "-a", f"v{n}", "-m", f"v{n}")
    url = "file://" + str(up)

    made = []

    def cache(tag):                                   # provision/bootstrap.sh : clone --depth 1 --branch <tag>
        made.append(tag)
        dst = tmp_path / f"cache-{tag}-{len(made)}"
        subprocess.run(["git", "clone", "--quiet", "--depth", "1", "--branch", tag, url, str(dst)],
                       check=True, capture_output=True, env=ENV)
        return dst

    def local_state(install):                         # ce qu'un golem qui a servi a écrit, hors git
        (install / "presets").mkdir(exist_ok=True)
        (install / "presets" / "mine.json").write_text('{"id": "mine"}')
        (install / "config").mkdir(exist_ok=True)
        (install / "config" / "io.json").write_text('{"card": "x"}')

    return type("W", (), {"up": up, "url": url, "cache": staticmethod(cache), "tmp": tmp_path,
                          "local_state": staticmethod(local_state)})


def state_kept(install):
    return ((install / "presets" / "mine.json").read_text() == '{"id": "mine"}'
            and (install / "config" / "io.json").read_text() == '{"card": "x"}')


def step(src, target):
    import installer.platform_linux as PL
    ctx = Ctx()
    return PL.step_source(ctx, str(src), str(target)), ctx


def test_install_line_over_an_install_made_by_the_install_line(world):
    """LE CAS QUI CASSAIT : install posée par la ligne d'installation (clone du cache, HEAD détachée sur le tag,
    profondeur 1), ligne relancée avec la release suivante."""
    install = world.tmp / "golem"
    subprocess.run(["git", "clone", "--quiet", str(world.cache("v1")), str(install)], check=True, capture_output=True, env=ENV)
    assert git(install, "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"          # détachée : la prémisse du test
    world.local_state(install)
    rc, ctx = step(world.cache("v2"), install)
    assert rc == 0, ctx.lines
    assert (install / "code.py").read_text() == "VERSION = 2\n"
    assert git(install, "describe", "--tags", "--exact-match") == "v2"           # la version se lit
    assert state_kept(install)


def test_over_an_install_that_came_from_an_archive(world):
    """ensure_git_repo : init, fetch du tag en profondeur 1, reset — une BRANCHE posée exactement sur le tag."""
    install = world.tmp / "golem"
    shutil.copytree(world.cache("v1"), install, ignore=shutil.ignore_patterns(".git"))
    git(install, "-c", "init.defaultBranch=main", "init", "-q")
    git(install, "remote", "add", "origin", world.url)
    git(install, "fetch", "-q", "--depth", "1", "origin", "refs/tags/v1:refs/tags/v1")
    git(install, "reset", "-q", "v1")
    assert git(install, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    world.local_state(install)
    rc, ctx = step(world.cache("v2"), install)
    assert rc == 0, ctx.lines
    assert (install / "code.py").read_text() == "VERSION = 2\n"
    assert state_kept(install)


def test_over_an_install_updated_by_the_update_button(world):
    """Le bouton Update : un clone complet, `git checkout <tag>`."""
    install = world.tmp / "golem"
    subprocess.run(["git", "clone", "--quiet", world.url, str(install)], check=True, capture_output=True, env=ENV)
    git(install, "checkout", "-q", "v1")
    rc, ctx = step(world.cache("v2"), install)
    assert rc == 0, ctx.lines
    assert (install / "code.py").read_text() == "VERSION = 2\n"


def test_a_branch_behind_the_release_fast_forwards(world):
    """Comme avant : un clone sur sa branche, en retard, avance — et reste sur sa branche."""
    install = world.tmp / "golem"
    subprocess.run(["git", "clone", "--quiet", world.url, str(install)], check=True, capture_output=True, env=ENV)
    git(install, "reset", "-q", "--hard", "v1")
    full = world.tmp / "src-full"                      # un installateur lancé depuis un clone complet (GOLEM_SRC)
    subprocess.run(["git", "clone", "--quiet", world.url, str(full)], check=True, capture_output=True, env=ENV)
    rc, ctx = step(full, install)
    assert rc == 0, ctx.lines
    assert git(install, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert (install / "code.py").read_text() == "VERSION = 2\n"


def test_a_branch_with_its_own_commits_is_refused_and_untouched(world):
    """Le travail de quelqu'un : on ne le déplace pas, et on le dit."""
    install = world.tmp / "golem"
    subprocess.run(["git", "clone", "--quiet", world.url, str(install)], check=True, capture_output=True, env=ENV)
    git(install, "reset", "-q", "--hard", "v1")
    (install / "mine.py").write_text("x = 1\n")
    git(install, "add", "-A")
    git(install, "commit", "-q", "-m", "my work")
    head = git(install, "rev-parse", "HEAD")
    rc, ctx = step(world.cache("v2"), install)
    assert rc != 0
    assert git(install, "rev-parse", "HEAD") == head
    assert (install / "code.py").read_text() == "VERSION = 1\n"
    assert any("nothing was changed" in ln for ln in ctx.lines), ctx.lines


def test_a_hand_edited_tracked_file_stops_the_switch_without_being_overwritten(world):
    install = world.tmp / "golem"
    subprocess.run(["git", "clone", "--quiet", str(world.cache("v1")), str(install)], check=True, capture_output=True, env=ENV)
    (install / "code.py").write_text("VERSION = 'mine'\n")
    rc, ctx = step(world.cache("v2"), install)
    assert rc != 0
    assert (install / "code.py").read_text() == "VERSION = 'mine'\n"


def test_same_release_again_changes_nothing(world):
    install = world.tmp / "golem"
    subprocess.run(["git", "clone", "--quiet", str(world.cache("v2")), str(install)], check=True, capture_output=True, env=ENV)
    world.local_state(install)
    rc, ctx = step(world.cache("v2"), install)
    assert rc == 0, ctx.lines
    assert any("already at this release" in ln for ln in ctx.lines)
    assert state_kept(install)



def test_the_installer_release_wins_when_its_copy_holds_several_tags(world):
    """Un installateur lancé d'un clone complet porte TOUS les tags : c'est son HEAD qui s'installe, pas le premier tag
    rapporté (FETCH_HEAD est réécrit par chaque fetch — l'étape lisait le mauvais commit)."""
    install = world.tmp / "golem"
    subprocess.run(["git", "clone", "--quiet", str(world.cache("v1")), str(install)], check=True, capture_output=True, env=ENV)
    full = world.tmp / "src-full"
    subprocess.run(["git", "clone", "--quiet", world.url, str(full)], check=True, capture_output=True, env=ENV)
    (full / "code.py").write_text("VERSION = 3\n")
    git(full, "commit", "-q", "-am", "release 3")
    git(full, "tag", "-a", "v3", "-m", "v3")
    rc, ctx = step(full, install)
    assert rc == 0, ctx.lines
    assert (install / "code.py").read_text() == "VERSION = 3\n"
    assert git(install, "describe", "--tags", "--exact-match") == "v3"
