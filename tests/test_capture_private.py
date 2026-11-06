# SPDX-License-Identifier: GPL-3.0-or-later
"""Une capture de plugin reste privée (2026-10-11 ; docs/plugin-capture.md §12) : son pack porte `provenance` et
`private`, et à l'installation sur un autre rack l'entrée du catalogue les retrouve."""
from bridge import tones_sync, tones_jobs


def test_le_pack_d_une_capture_dit_sa_provenance_et_reste_prive(monkeypatch):
    import sys
    monkeypatch.setattr(sys, "platform", "win32")
    entry = {"id": "cap-example", "title": "Example Amp Suite", "brand": "Example Vendor", "source_group": "plugin-capture",
             "capture": {"plugin": "VST3: Example Amp Suite (Example Vendor)", "mode": "full", "at": "2026-10-10T22:00:00", "private": True}}
    p = tones_sync._provenance(entry)
    assert p["private"] is True
    assert p["provenance"] == {"kind": "plugin-capture", "plugin": "VST3: Example Amp Suite (Example Vendor)", "vendor": "Example Vendor",
                               "os": "windows", "at": "2026-10-10T22:00:00"}
    assert tones_sync._provenance({"id": "t3k-1", "title": "Marshall", "source_group": "t3k"}) == {}   # un tone ordinaire : rien


def test_a_l_installation_la_capture_revient_privee_avec_son_histoire():
    pack = {"uid": "local:cap-example", "provenance": {"kind": "plugin-capture", "plugin": "VST3: Example Amp Suite (Example Vendor)", "os": "linux", "at": "x"}}
    d = tones_jobs._private_from_pack(pack)
    assert d["private"] is True and d["source_group"] == "plugin-capture"
    assert d["capture"] == {"plugin": "VST3: Example Amp Suite (Example Vendor)", "at": "x", "private": True, "os": "linux"}
    assert tones_jobs._private_from_pack({"uid": "local:cap-x", "private": True}) ["private"] is True   # le cliquet sans provenance
    assert tones_jobs._private_from_pack({"uid": "t3k:1"}) == {}
