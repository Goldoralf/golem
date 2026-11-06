# SPDX-License-Identifier: GPL-3.0-or-later
"""La licence REAPER (2026-10-16) : UNE écriture (bridge/reaper_license.py) partagée par Settings ▸ Licenses et par
l'écran 3 de l'installateur, la ligne REAPER de l'écran de chargement (boot_progress). Tout se passe dans tmp_path :
GOLEM_REAPER_RESOURCE_DIR et GOLEM_RECEIPT — jamais le vrai ~/.config/REAPER ni le vrai reçu."""
import asyncio
import importlib.util
import json
import os
import stat
import sys
import threading
import urllib.request

import pytest

from bridge import boot_progress, install_receipt, reaper_license as RL, routes_system
from bridge import config as C

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET = "golem-test-licence\nNAME=nobody\nKEY=0123456789abcdef"


@pytest.fixture
def res(tmp_path, monkeypatch):
    d = tmp_path / "res" / "REAPER"                     # n'existe pas encore : l'écriture le crée
    monkeypatch.setenv("GOLEM_REAPER_RESOURCE_DIR", str(d))
    monkeypatch.setenv("GOLEM_RECEIPT", str(tmp_path / "receipt" / "install-receipt.json"))
    return d


# ── le module partagé ─────────────────────────────────────────────────────────────────────────────────
def test_le_bridge_et_le_module_partage_visent_le_meme_dossier(res):
    assert C.reaper_resource_dir() == RL.resource_dir() == str(res)
    assert routes_system._reaper_license_path() == RL.path() == str(res / "reaper-license.rk")


@pytest.mark.parametrize("plat,env,want", [
    ("linux", {"HOME": "/h"}, "/h/.config/REAPER"),
    ("darwin", {"HOME": "/h"}, "/h/Library/Application Support/REAPER"),
    ("win32", {"USERPROFILE": "C:/u", "APPDATA": "C:/u/AppData/Roaming"}, os.path.join("C:/u/AppData/Roaming", "REAPER")),
])
def test_le_dossier_de_ressources_par_systeme(monkeypatch, plat, env, want):
    monkeypatch.delenv("GOLEM_REAPER_RESOURCE_DIR", raising=False)
    monkeypatch.setattr(sys, "platform", plat)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    assert RL.resource_dir() == want


def test_ecrit_cree_le_dossier_en_0600_et_note_l_avant(res):
    seen = []
    p = RL.write("  " + SECRET + "\n\n", prior=lambda k, v: seen.append((k, v)))
    assert p == str(res / "reaper-license.rk")
    assert open(p, encoding="utf-8").read() == SECRET + "\n"
    if os.name == "posix":
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert not os.path.exists(p + ".tmp")
    RL.write("autre licence", prior=lambda k, v: seen.append((k, v)))
    assert seen == [("reaper.license_present", False), ("reaper.license_present", True)]
    assert RL.present()


def test_un_recu_qui_leve_ne_fait_pas_echouer_l_ecriture(res):
    def boom(k, v):
        raise RuntimeError("reçu cassé")
    RL.write(SECRET, prior=boom)
    assert RL.present()


@pytest.mark.parametrize("bad,why", [
    (None, "empty license"), ("", "empty license"), ("   \n", "empty license"), (42, "must be text"),
    ("a\x00b", "not a text file"),
    # un id court : sans lui, pytest met les 64 Ko dans PYTEST_CURRENT_TEST et Windows refuse la variable (> 32 767)
    pytest.param("x" * (64 * 1024 + 1), "larger than 64 KB", id="64KB+1"),
])
def test_validation_minimale(res, bad, why):
    lic, err = RL.clean(bad)
    assert lic is None and why in err
    with pytest.raises(ValueError):
        RL.write(bad)
    assert not RL.present() and not res.exists()


def test_64_ko_pile_passe(res):
    assert RL.clean("x" * (64 * 1024)) == ("x" * (64 * 1024), None)


# ── le bridge : la route de Settings ▸ Licenses, et l'écran de chargement ─────────────────────────────
def test_la_route_du_bridge_ecrit_par_le_module_partage_et_ne_renvoie_jamais_la_licence(res, monkeypatch):
    seen = []
    monkeypatch.setattr(install_receipt, "prior", lambda k, v: seen.append((k, v)))
    monkeypatch.setattr(routes_system.sys, "platform", "linux")
    out = asyncio.run(routes_system.reaper_license_set({"license": SECRET}))
    assert out == {"ok": True, "restart_needed": True}
    assert (res / "reaper-license.rk").read_text() == SECRET + "\n"
    assert seen == [("reaper.license_present", False)]
    st = routes_system.reaper_license_status()
    assert st == {"present": True} and SECRET not in json.dumps(st)
    big = asyncio.run(routes_system.reaper_license_set({"license": "x" * 70000}))
    assert big.status_code == 400 and b"64 KB" in big.body


def test_la_ligne_reaper_du_chargement_suit_la_presence(res, monkeypatch):
    monkeypatch.setattr(routes_system.sys, "platform", "linux")
    boot_progress.refresh_reaper_license()
    assert boot_progress.doc()["services"]["reaper"] == {"present": False, "state": None, "ok": False}
    asyncio.run(routes_system.reaper_license_set({"license": SECRET}))     # la route rafraîchit la ligne elle-même
    sv = boot_progress.doc()["services"]["reaper"]
    assert sv == {"present": True, "state": None, "ok": True}
    assert SECRET not in json.dumps(boot_progress.doc())


def test_windows_un_fichier_refuse_par_ce_reaper_reste_en_evaluation(res, monkeypatch):
    from bridge import desktop_reaper
    monkeypatch.setattr(routes_system.sys, "platform", "win32")
    monkeypatch.setattr(desktop_reaper, "license_state", lambda: "evaluation")
    RL.write(SECRET)
    boot_progress.refresh_reaper_license()
    assert boot_progress.doc()["services"]["reaper"] == {"present": True, "state": "evaluation", "ok": False}


# ── l'installateur, écran 3 ───────────────────────────────────────────────────────────────────────────
def _server():
    if sys.platform != "linux":
        pytest.skip("installateur testé sous Linux")
    spec = importlib.util.spec_from_file_location("golem_installer_lic", os.path.join(ROOT, "installer", "server.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _receipt_mod():
    spec = importlib.util.spec_from_file_location("golem_receipt_t", os.path.join(ROOT, "provision", "receipt.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_installateur_ecrit_au_meme_endroit_sans_journaliser_la_licence(res):
    m = _server()
    m.S["dry"] = False
    out = m.license_save({"license": SECRET})
    assert out == {"ok": True, "present": True}
    assert (res / "reaper-license.rk").read_text() == SECRET + "\n"
    assert m.license_present() is True
    journal = json.dumps(m.S["log"])
    assert "REAPER license saved" in journal
    for part in SECRET.splitlines():
        assert part not in journal
    assert m.license_save({"license": "  "}) == {"ok": False, "error": "empty license"}


def test_installateur_recu_en_attente_puis_verse_le_premier_gagne(res):
    m = _server()
    m.S["dry"] = False
    R = _receipt_mod()
    assert not R.exists()
    m.license_save({"license": SECRET})              # écran 3 : le reçu n'existe pas encore -> en attente
    m.license_save({"license": SECRET})              # la 2e écriture voit la 1re : le premier gagne
    assert not R.exists() and m._PENDING_PRIOR == {"reaper.license_present": False}
    R.set_root(str(res.parent))                      # l'étape source crée le reçu (set-root)
    assert R.exists()
    m.flush_priors()
    assert R.get_prior("reaper.license_present") is False and m._PENDING_PRIOR == {}
    m.license_save({"license": SECRET})              # reçu présent : écrit tout de suite, mais le premier gagne
    assert R.get_prior("reaper.license_present") is False


def test_installateur_dry_ne_touche_a_rien(res):
    m = _server()
    m.S["dry"] = True
    assert m.license_present() is False
    out = m.license_save({"license": SECRET})
    assert out == {"ok": True, "dry": True, "present": True}
    assert not res.exists() and m.license_present() is True and m._PENDING_PRIOR == {}
    assert not _receipt_mod().exists()


def test_installateur_http_presence_seulement(res):
    m = _server()
    m.S["dry"] = False
    httpd = m.ThreadingHTTPServer(("127.0.0.1", 0), m.H)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    hdr = {"X-Golem-Token": m.S["token"], "Content-Type": "application/json"}

    def call(path, body=None):
        req = urllib.request.Request(base + path, headers=hdr, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.read().decode()
    try:
        assert json.loads(call("/api/reaper"))["license_present"] is False
        posted = call("/api/reaper/license", {"license": SECRET})
        assert json.loads(posted)["ok"] is True
        everything = posted + call("/api/reaper") + call("/api/state") + call("/api/log?since=0")
        assert json.loads(call("/api/reaper"))["license_present"] is True
        for part in SECRET.splitlines():
            assert part not in everything
    finally:
        httpd.shutdown()
