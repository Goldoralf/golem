# SPDX-License-Identifier: GPL-3.0-or-later
"""Settings ▸ About ▸ Golem Engine (2026-11-27) : l'épingle montrée est celle du système qui tourne — Linux lit
provision/golem_engine.py VERSION, Windows son pins.json, qui avance à son propre pas."""
import json
import os

from bridge import routes_system as R
from provision import golem_engine as ge

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_linux_montre_la_version_du_module(monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "linux")
    d = R.golem_engine_about()
    assert d["pinned"] == ge.VERSION
    assert d["license"] == "GPL-2.0-or-later" and d["sources_url"].startswith("https://github.com/Goldoralf/golem-engine")


def test_windows_montre_l_epingle_de_son_pins_json(monkeypatch):
    monkeypatch.setattr(R.sys, "platform", "win32")
    want = json.load(open(os.path.join(ROOT, "provision", "windows", "pins.json"), encoding="utf-8"))["golem_engine"]["version"]
    assert R.golem_engine_about()["pinned"] == want
