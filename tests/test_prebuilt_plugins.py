# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugins Linux précompilés (provision/fetch-prebuilt.sh, dépôt public Goldoralf/golem-binaries, 2026-10-23)."""
import os
import re
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROV = os.path.join(ROOT, "provision")


def _read(name):
    return open(os.path.join(PROV, name), encoding="utf-8").read()


def test_chaque_archive_precompilee_demandee_est_epinglee():
    base = re.search(r'GOLEM_PREBUILT_BASE:-([^}]+)\}', _read("fetch-prebuilt.sh")).group(1)
    pinned = {ln.split()[1] for ln in _read("downloads.sha256").splitlines() if ln and not ln.startswith("#")}
    assets = set()
    for script in ("install-zconvo.sh", "install-nam.sh", "install-prisma.sh", "install-spectral.sh"):
        assets |= set(re.findall(r"\b(?:prebuilt|pre) ([A-Za-z_.-]+\.(?:lv2|vst3|clap)) ", _read(script)))
    assert len(assets) == 9
    for a in assets:
        assert f"{base}/{a}.tar.gz" in pinned, a


def test_les_binaires_viennent_du_depot_public():
    # un dépôt PRIVÉ répond 404 à un installateur non connecté à GitHub : sfizz et NAM l'ont montré
    sums = _read("downloads.sha256") + _read("windows/pins.json") + _read("macos/pins.json")
    assert "Goldoralf/golem/releases/download" not in sums


def test_freeze_precompile_suit_sa_source():
    # si plugins/ a bougé depuis la release, le script compile Freeze au lieu de poser un binaire d'une autre source
    sh = _read("install-spectral.sh")
    pinned = re.search(r'FREEZE_SRC_SHA="([0-9a-f]{64})"', sh).group(1)
    cur = subprocess.run("cat Cargo.lock Cargo.toml golem_freeze/Cargo.toml golem_freeze/src/*.rs | sha256sum",
                         shell=True, cwd=os.path.join(ROOT, "plugins"), capture_output=True, text=True).stdout[:64]
    if cur != pinned:
        import warnings
        warnings.warn("plugins/ a changé depuis linux-plugins-v1 : GoleM Freeze sera compilé à l'installation "
                      "(publier une nouvelle release golem-binaries et mettre à jour FREEZE_SRC_SHA)")
    assert re.fullmatch(r"[0-9a-f]{64}", pinned)
