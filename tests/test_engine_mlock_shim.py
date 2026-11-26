# SPDX-License-Identifier: GPL-3.0-or-later
"""Le verrou mémoire du moteur (provision/golem-mlock.c) : préchargé seulement sous Linux, s'il existe, et coupable."""
import sys

from bridge.engine import ardour


def test_mlock_shim_present_on_linux(tmp_path, monkeypatch):
    so = tmp_path / "libgolem-mlock.so"
    so.write_bytes(b"")
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.delenv("GOLEM_ENGINE_MLOCK", raising=False)
    assert ardour.mlock_shim(str(so)) == str(so)


def test_mlock_shim_absent_off_or_elsewhere(tmp_path, monkeypatch):
    so = tmp_path / "libgolem-mlock.so"
    monkeypatch.setattr(sys, "platform", "linux")
    assert ardour.mlock_shim(str(so)) is None                     # pas compilé : le moteur part sans
    so.write_bytes(b"")
    monkeypatch.setenv("GOLEM_ENGINE_MLOCK", "0")
    assert ardour.mlock_shim(str(so)) is None                     # coupé
    monkeypatch.delenv("GOLEM_ENGINE_MLOCK")
    monkeypatch.setattr(sys, "platform", "win32")
    assert ardour.mlock_shim(str(so)) is None                     # Linux seulement
