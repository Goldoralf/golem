# SPDX-License-Identifier: GPL-3.0-or-later
"""Plugins Linux précompilés (provision/fetch-prebuilt.sh, dépôt public Goldoralf/golem-binaries, 2026-10-23)."""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROV = os.path.join(ROOT, "provision")


def _read(name):
    return open(os.path.join(PROV, name), encoding="utf-8").read()


def test_chaque_archive_precompilee_demandee_est_epinglee():
    base = re.search(r'GOLEM_PREBUILT_BASE:-([^}]+)\}', _read("fetch-prebuilt.sh")).group(1)
    pinned = {ln.split()[1] for ln in _read("downloads.sha256").splitlines() if ln and not ln.startswith("#")}
    assets = set()
    for script in ("install-zconvo.sh", "install-nam.sh", "install-spectral.sh"):
        assets |= set(re.findall(r"\b(?:prebuilt|pre) ([A-Za-z_.-]+\.(?:lv2|vst3|clap)) ", _read(script)))
    # GoleM Freeze n'est plus posé depuis le 2026-11-15 ; Prisma et Spectral Compressor depuis le 2026-11-27
    assert len(assets) == 4
    for a in assets:
        assert f"{base}/{a}.tar.gz" in pinned, a


def test_les_binaires_viennent_du_depot_public():
    # un dépôt PRIVÉ répond 404 à un installateur non connecté à GitHub : sfizz et NAM l'ont montré
    sums = _read("downloads.sha256") + _read("windows/pins.json") + _read("macos/pins.json")
    assert "Goldoralf/golem/releases/download" not in sums


def test_freeze_n_est_plus_pose():
    # le bloc freeze est retiré (catalogue v48) : ni précompilé ni compilé ; Spectral Compressor et Rust non plus
    # depuis le 2026-11-27 (gfx-spectralcomp) — seul PaulXStretch reste
    sh = "\n".join(ln for ln in _read("install-spectral.sh").splitlines() if not ln.lstrip().startswith("#"))
    assert "Freeze" not in sh and "golem_freeze" not in sh and "FREEZE" not in sh
    assert "spectral_compressor" not in sh and "Spectral-Compressor" not in sh and "rustup" not in sh and "cargo" not in sh
    assert "PaulXStretch.vst3" in sh
    assert not os.path.exists(os.path.join(PROV, "install-prisma.sh"))
    assert "GoleM-Freeze" not in _read("downloads.sha256")
    assert not os.path.exists(os.path.join(ROOT, "plugins", "golem_freeze"))
