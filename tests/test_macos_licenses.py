# SPDX-License-Identifier: GPL-3.0-or-later
"""Licenses sous macOS (docs/platforms.md, M3) : REAPER.app lu, Libraries par `check_mac`."""
import json
import os
import plistlib

from bridge import libraries, reaper_update

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_macos_reads_check_mac_and_says_linux_only(tmp_path):
    man = tmp_path / "components.json"
    man.write_text(json.dumps({"components": [
        {"id": "reaper", "name": "R", "license": "Commercial", "url": "u", "kind": "engine",
         "check": {"glob": ["~/opt/REAPER/reaper"]}, "check_win": {"glob": ["x"]},
         "check_mac": {"glob": ["/Applications/REAPER.app"]}},
        {"id": "calf", "name": "C", "license": "LGPL", "url": "u", "kind": "plugin", "check": {"dpkg": ["calf-plugins"]}},
        {"id": "fastapi", "name": "F", "license": "MIT", "url": "u", "kind": "python", "check": {"pip": ["fastapi"]}}]}))
    seen = []
    r = libraries.report(root="/r", home="/h", manifest=str(man), dpkg={}, pip_names={"fastapi"},
                         exists=lambda p: seen.append(p) or True, platform="darwin")
    st = {c["id"]: (c["installed"], c.get("only")) for c in r["components"]}
    assert st == {"reaper": (True, None), "calf": (None, "linux"), "fastapi": (True, None)}
    assert seen == [["/Applications/REAPER.app"]] and "check_mac" not in r["components"][0]


def test_every_desktop_component_has_a_mac_check():
    """Ce que GoleM vérifie sous Windows, il le vérifie sous macOS : aucun composant desktop oublié."""
    comps = libraries.load_manifest()
    missing = [c["id"] for c in comps if "check_win" in c and "check_mac" not in c]
    assert missing == []
    for c in comps:
        for pat in (c.get("check_mac") or {}).get("glob", []):
            assert "%" not in pat and "\\" not in pat, (c["id"], pat)


def _app(tmp_path, version):
    app = tmp_path / "REAPER.app"
    (app / "Contents" / "MacOS").mkdir(parents=True)
    (app / "Contents" / "MacOS" / "REAPER").write_text("")
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump({"CFBundleShortVersionString": version}, f, fmt=plistlib.FMT_BINARY)
    return app


def _mac(monkeypatch, app):
    monkeypatch.setattr(reaper_update, "MACOS", True)
    monkeypatch.setattr(reaper_update, "WINDOWS", False)
    monkeypatch.setenv("REAPER_BIN", str(app / "Contents" / "MacOS" / "REAPER"))
    monkeypatch.setattr(reaper_update, "upstream_check", lambda force=False: None)


def test_the_engine_version_is_read_from_the_app_bundle(tmp_path, monkeypatch):
    app = _app(tmp_path, "7.79")
    _mac(monkeypatch, app)
    assert reaper_update.installed_version() == "7.79"
    st = reaper_update.status(check=False)
    assert (st["installed"], st["pinned"], st["status"]) == ("7.79", "7.79", "up-to-date")
    assert st["versions"] == [{"version": "7.79", "active": True}]
    assert st["can_update"] is False and "macOS" in st["update_unavailable_why"]


def test_an_older_engine_is_seen_but_never_updated_from_golem(tmp_path, monkeypatch):
    _mac(monkeypatch, _app(tmp_path, "7.27"))
    assert reaper_update.status(check=False)["status"] == "update-available"
    ok, why = reaper_update.start_update()
    assert not ok and why == reaper_update.MAC_UNSUPPORTED
    assert reaper_update.start_switch("7.27") == (False, reaper_update.MAC_UNSUPPORTED)


def test_no_app_is_not_installed(tmp_path, monkeypatch):
    _mac(monkeypatch, tmp_path / "REAPER.app")
    assert reaper_update.status(check=False)["status"] == "not-installed"


def test_macos_pins_match_windows_reaper_and_ci_nam():
    mac = json.load(open(os.path.join(ROOT, "provision", "macos", "pins.json"), encoding="utf-8"))
    win = json.load(open(os.path.join(ROOT, "provision", "windows", "pins.json"), encoding="utf-8"))
    assert mac["reaper"]["version"] == win["reaper"]["version"]
    assert mac["nam_vst3"]["version"] == win["nam_vst3"]["version"]
    for entry in (mac["reaper"], mac["nam_vst3"]):
        assert len(entry["sha256"]) == 64 and entry["url"].endswith(".dmg")
