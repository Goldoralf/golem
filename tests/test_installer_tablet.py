# SPDX-License-Identifier: GPL-3.0-or-later
"""L'installateur n'a plus de case « boîte dédiée » ; son écran Done offre « Open golem » et « Continue on a tablet »
(docs/installer.md §4, FIXÉ 2026-10-16). En --dry tout est simulé : aucune requête vers :8770, rien n'est lancé."""
import importlib.util
import os
import subprocess
import sys
import urllib.request

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _src(*p):
    return open(os.path.join(ROOT, *p), encoding="utf-8").read()


def _server():
    if sys.platform != "linux":
        pytest.skip("le serveur de l'installateur est chargé avec son module Linux")
    spec = importlib.util.spec_from_file_location("golem_installer_tab", os.path.join(ROOT, "installer", "server.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.DB.reset()
    m.TAB.update(phase="idle", error=None, info=None, t0=None)
    return m


@pytest.fixture
def no_http(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("HTTP request in dry mode")
    monkeypatch.setattr(urllib.request, "urlopen", boom)

    def no_proc(*a, **k):
        raise AssertionError(f"process started in dry mode: {a}")
    monkeypatch.setattr(subprocess, "Popen", no_proc)


def test_plus_de_case_boite_dediee():
    js = _src("installer", "ui", "installer.js")
    assert "Dedicated machine" not in js and "autostart" not in js and 'type="checkbox" checked=${!!st.autostart}' not in js
    assert "['where', 'Folder']" in js
    m = _server()
    assert "autostart" not in m.S
    for name in ("platform_linux.py", "platform_windows.py", "platform_macos.py"):
        src = _src("installer", name)
        assert "install-autostart" not in src and "harden.sh" not in src and '"autostart", "on"' not in src, name
    assert "-autostart" not in _src("installer", "dry_step.py")


def test_les_deux_lanceurs_sont_toujours_poses():
    lin = _src("installer", "platform_linux.py")
    prof = lin.split("def step_profile(ctx, target):", 1)[1].split("\ndef ", 1)[0]
    assert "install-desktop.sh" in prof and "if " not in prof.replace('if S["dry"]', "")      # sans condition
    # install-desktop.sh pose le lanceur golem (desktop + server) ; Windows/macOS : `provision.desktop shortcuts`
    assert "Exec=$BIN/golem server" in _src("provision", "install-desktop.sh")
    for name in ("platform_windows.py", "platform_macos.py"):
        prof = _src("installer", name).split("def step_profile(ctx, target):", 1)[1].split("\ndef ", 1)[0]
        assert '"shortcuts"' in prof, name


def test_config_ignore_autostart():
    m = _server()
    m.S["dry"] = True
    assert "autostart" not in m.S


def test_done_continue_on_a_tablet_en_dry(no_http):
    m = _server()
    m.S["dry"] = True
    r = m.tablet_start()
    assert r["phase"] == "ready" and r["dry"] is True
    i = r["info"]
    assert i["url"].startswith("http://") and i["pair_url"].endswith("/app/pair.html")
    assert i["code"] and not i["paired"]
    # le code n'est créé qu'une fois : relire l'état ne le change pas
    assert m.tablet_state()["info"]["code"] == i["code"]
    assert m.tablet_start()["info"]["code"] == i["code"]
    body, ctype = m.tablet_qr()
    assert ctype == "image/svg+xml" and body.startswith(b"<svg")


def test_done_golem_muet_en_dry(no_http, monkeypatch):
    m = _server()
    m.S["dry"] = True
    monkeypatch.setenv("GOLEM_INSTALLER_DRY_BRIDGE", "down")
    r = m.tablet_start()
    assert r["phase"] == "error" and "not answering" in r["error"]


def test_done_demarre_golem_server_s_il_ne_repond_pas(monkeypatch):
    m = _server()
    m.S["dry"] = False
    started = []
    monkeypatch.setattr(m, "_tablet_info", lambda: (_ for _ in ()).throw(ConnectionError("down")))
    monkeypatch.setattr(m.P, "bridge_start", lambda ctx: started.append(ctx.S["dir"]) or None, raising=False)
    r = m.tablet_start()
    assert r["phase"] == "starting"
    import time
    for _ in range(50):
        if started:
            break
        time.sleep(0.02)
    assert started
    # golem répond : la page qui interroge voit l'adresse
    monkeypatch.setattr(m, "_tablet_info", lambda: {"url": "http://x.local:8770/app/", "named": True,
                                                     "pair_url": "http://x.local:8770/app/pair.html", "code": "1",
                                                     "paired": False})
    assert m.tablet_state()["phase"] == "ready"


def test_linux_bridge_start_lance_golem_server(monkeypatch, tmp_path):
    if sys.platform != "linux":
        pytest.skip("Linux")
    sys.path.insert(0, os.path.join(ROOT, "installer"))
    try:
        spec = importlib.util.spec_from_file_location("pl_t", os.path.join(ROOT, "installer", "platform_linux.py"))
        P = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(P)
    finally:
        sys.path.remove(os.path.join(ROOT, "installer"))
    (tmp_path / "provision").mkdir()
    (tmp_path / "provision" / "golem").write_text("#!/bin/sh\n")
    calls = []
    monkeypatch.setattr(P.subprocess, "Popen", lambda argv, **k: calls.append((argv, k)))
    ctx = type("Ctx", (), {"S": {"dir": str(tmp_path)}})()
    assert P.bridge_start(ctx) is None
    assert calls[0][0] == [str(tmp_path / "provision" / "golem"), "server"]
    assert calls[0][1]["start_new_session"] is True


def test_done_screen_porte_les_deux_sorties():
    js = _src("installer", "ui", "installer.js")
    done = js.split("done: () => html`", 1)[1]
    assert "Open golem" in done and "Continue on a tablet" in done and "tabletStart" in done
    assert "/api/tablet" in js and "/api/tablet/qr" in js
    # la page n'appelle jamais golem elle-même
    assert ":8770/api" not in js
