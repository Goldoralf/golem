# SPDX-License-Identifier: GPL-3.0-or-later
"""La cause d'un clic sous le Golem Engine (docs/health.md §2 bis) : un pilote qui retarde les cycles, ou un patch trop
lourd pour le buffer — dite par Health ▸ Dropouts, d'après les compteurs du patch 16 du moteur."""
from types import SimpleNamespace

from bridge import health


def test_la_cause_vient_des_compteurs_du_moteur():
    assert health.dropout_cause({"late_cycles": 10, "late_starts": 8}) == "driver"
    assert health.dropout_cause({"late_cycles": 10, "late_starts": 2}) == "load"
    assert health.dropout_cause({"late_cycles": 0, "late_starts": 0}) is None
    assert health.dropout_cause({"xruns": 3}) is None                     # REAPER, ou un moteur d'avant le patch
    assert health.dropout_cause(None) is None


def test_le_fait_dropouts_dit_le_pilote(monkeypatch):
    monkeypatch.setattr(health, "_engine_status", lambda: {"late_cycles": 12, "late_starts": 11})
    st = SimpleNamespace(xruns=12, xruns_recent=12, xruns_last=None)
    f = health._f_dropouts(st)
    assert f["level"] == "bad" and "a driver" in f["text"] and "LatencyMon" in f["text"]
    monkeypatch.setattr(health, "_engine_status", lambda: {})
    assert "driver" not in health._f_dropouts(st)["text"]                 # rien de compté : on n'invente pas de cause
