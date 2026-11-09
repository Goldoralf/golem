# SPDX-License-Identifier: GPL-3.0-or-later
"""La liste des paquets apt (provision/packages.txt, lue par provision/lib-packages.sh), 2026-11-03 : sous Ubuntu 26.04,
invada-studio-plugins-lv2 a quitté la distribution et l'unique `apt-get install` de toute la liste faisait mourir
l'install en phase 1. Un paquet « nom? » est optionnel (écarté et dit s'il manque) ; un essentiel manquant reste fatal.
Les tests passent par bash, avec un faux apt-cache dans le PATH : aucun apt n'est nécessaire."""
import os
import shutil
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIB = os.path.join(ROOT, "provision", "lib-packages.sh")
LIST = os.path.join(ROOT, "provision", "packages.txt")

# sous Windows, `bash` est le lanceur de WSL, sans distribution sur le runner (CI Desktop tests, 2026-11-09)
pytestmark = pytest.mark.skipif(shutil.which("bash") is None or sys.platform == "win32", reason="un vrai bash")

# le faux apt-cache : « dispo » a un candidat, « retire » est connu sans version, tout le reste est inconnu (sortie vide)
FAKE_APT_CACHE = """#!/bin/sh
case "$2" in
  dispo*) printf 'dispo:\\n  Installed: (none)\\n  Candidate: 1.0-1\\n  Version table:\\n' ;;
  retire*) printf 'retire:\\n  Installed: (none)\\n  Candidate: (none)\\n  Version table:\\n' ;;
esac
"""


def _bash(script, tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    fake = bindir / "apt-cache"
    fake.write_text(FAKE_APT_CACHE)
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}")
    r = subprocess.run(["bash", "-c", f"set -euo pipefail; . '{LIB}'; {script}"],
                       capture_output=True, text=True, env=env, check=True)
    return r.stdout


def _parse(path, tmp_path):
    out = _bash(f"golem_packages_parse '{path}'", tmp_path)
    return [tuple(line.split("\t")) for line in out.splitlines()]


def test_le_point_d_interrogation_et_les_commentaires(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("# entête\n\nalpha\nbeta?    # inline, avec un ? dans le commentaire\n  gamma?\ndelta # x?\n")
    assert _parse(f, tmp_path) == [("alpha", "req"), ("beta", "opt"), ("gamma", "opt"), ("delta", "req")]


def test_resolution_contre_l_index(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("dispo-a\ndispo-b?\nretire-opt?\ninconnu-opt?\nretire-req\ninconnu-req\n")
    out = _bash(f"golem_packages_resolve '{f}'; "
                "echo \"I:${PKGS[*]}\"; echo \"S:${PKGS_SKIPPED[*]}\"; echo \"M:${PKGS_MISSING[*]}\"", tmp_path)
    assert out.splitlines() == ["I:dispo-a dispo-b", "S:retire-opt inconnu-opt", "M:retire-req inconnu-req"]


def test_rien_ne_manque_les_listes_vides_passent_set_u(tmp_path):
    f = tmp_path / "p.txt"
    f.write_text("dispo-a\n")
    out = _bash(f"golem_packages_resolve '{f}'; "
                "for p in \"${PKGS_SKIPPED[@]}\"; do echo \"S:$p\"; done; echo \"n=${#PKGS_MISSING[@]}\"", tmp_path)
    assert out.splitlines() == ["n=0"]


def test_la_vraie_liste(tmp_path):
    pkgs = dict(_parse(LIST, tmp_path))
    assert "invada-studio-plugins-lv2" not in pkgs                 # retiré : aucun bloc, et absent d'Ubuntu 26.04
    assert all("?" not in n for n in pkgs)
    # ce sans quoi golem ne démarre pas reste ESSENTIEL : son absence doit arrêter l'install
    for n in ("pipewire-audio", "pipewire-jack", "wireplumber", "python3-venv", "python3-pip", "git", "curl", "xvfb"):
        assert pkgs[n] == "req", n
    # les plugins de la distribution sont optionnels : un bloc muet, pas une install morte
    for n in ("lsp-plugins", "calf-plugins", "guitarix", "zam-plugins", "x42-plugins", "dragonfly-reverb", "ir.lv2",
              "ardour-lv2-plugins", "setbfree", "qpwgraph"):
        assert pkgs[n] == "opt", n


def test_install_sh_installe_et_declare_la_liste_filtree():
    src = open(os.path.join(ROOT, "provision", "install.sh"), encoding="utf-8").read()
    resolve = src.index('golem_packages_resolve "$HERE/packages.txt"')
    assert src.index("apt-get -o DPkg::Lock::Timeout=300 update") < resolve     # l'index d'abord
    assert resolve < src.index('receipt apt-requested "${PKGS[@]}"')            # le reçu dit la liste filtrée
    assert "mapfile -t PKGS" not in src                                         # plus de seconde lecture de la liste


# ── Chromium en paquet apt (Debian, Mint — 2026-11-03) : un vrai paquet est posé par apt ; le renvoi d'Ubuntu vers le
# snap (il dépend de snapd) est écarté, c'est alors le snap qu'install.sh pose ──
FAKE_APT_CHROMIUM = """#!/bin/sh
case "$FAKE_CHROMIUM:$1" in
  deb:policy|snap:policy) printf 'chromium:\\n  Installed: (none)\\n  Candidate: 1:120.0\\n' ;;
  none:policy) printf 'chromium:\\n  Installed: (none)\\n  Candidate: (none)\\n' ;;
  deb:depends) printf 'chromium\\n  Depends: libc6\\n  Depends: chromium-common\\n' ;;
  snap:depends) printf 'chromium\\n  PreDepends: debconf\\n  Depends: snapd\\n' ;;
esac
"""


@pytest.mark.parametrize("kind, expected", [("deb", "chromium"), ("snap", ""), ("none", ""), ("absent", "")])
def test_chromium_en_paquet_apt_seulement_si_c_est_un_vrai_paquet(tmp_path, kind, expected):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "apt-cache"
    fake.write_text(FAKE_APT_CHROMIUM)
    fake.chmod(0o755)
    env = dict(os.environ, PATH=f"{bindir}:{os.environ['PATH']}", FAKE_CHROMIUM=kind)
    r = subprocess.run(["bash", "-c", f"set -euo pipefail; . '{LIB}'; golem_chromium_deb"],
                       capture_output=True, text=True, env=env, check=True)
    assert r.stdout.strip() == expected


def test_install_sh_tente_apt_avant_le_snap():
    src = open(os.path.join(ROOT, "provision", "install.sh"), encoding="utf-8").read()
    i_deb, i_snap = src.index("golem_chromium_deb)"), src.index("sudo snap install chromium")
    assert i_deb < i_snap
    # le reçu : demandé ET photographié, pour que la désinstallation le propose comme tout paquet golem
    block = src[i_deb:i_snap]
    assert "receipt apt-requested \"$CHROMIUM_DEB\"" in block and "receipt apt-snapshot after" in block
