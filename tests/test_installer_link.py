# SPDX-License-Identifier: GPL-3.0-or-later
"""L'écran Connect de l'installateur (docs/installer.md §2 écran 7, §6) — 2026-10-15 : deux cartes à
l'installateur (golem.fm, TONE3000) au lieu de l'app dans un cadre. La page parle au serveur de l'installateur,
qui relaie vers golem une liste COURTE de routes (BRIDGE_ALLOW) ; en --dry, il n'envoie RIEN à :8770 (sur un poste
de dev, c'est le vrai rack) et joue installer/dry_bridge.py."""
import http.client
import importlib.util
import json
import os
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _server():
    if sys.platform != "linux":
        pytest.skip("l'écran Connect relayé est celui de Linux")
    spec = importlib.util.spec_from_file_location("golem_installer_link", os.path.join(ROOT, "installer", "server.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.DB.reset()
    return m


@pytest.fixture
def no_bridge(monkeypatch):
    """Toute requête urllib (le seul client HTTP du relais) est notée et refusée : en --dry, il n'y en a aucune."""
    calls = []

    def boom(req, *a, **k):
        calls.append(getattr(req, "full_url", req))
        raise AssertionError(f"HTTP request in dry mode: {calls[-1]}")
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    return calls


def test_le_relais_n_accepte_que_sa_liste_courte():
    m = _server()
    m.S["dry"] = True
    assert m.BRIDGE_ALLOW == {
        ("GET", "/api/integrations"), ("POST", "/api/integrations"), ("GET", "/api/golemfm/status"),
        ("POST", "/api/golemfm/pair"), ("GET", "/api/golemfm/pair/status"), ("GET", "/api/band"),
        ("POST", "/api/t3k/auth/start"), ("GET", "/api/t3k/auth/status"),
        ("GET", "/api/factory/captures"), ("POST", "/api/factory/captures/download"),
        # l'écran Done, « Continue on a tablet » (docs/installer.md §4, 2026-10-16)
        ("GET", "/api/network/open-url"), ("GET", "/api/auth/devices"), ("POST", "/api/auth/pair-code")}
    for method, path in (("POST", "/api/system/update"), ("POST", "/api/rig_recall"), ("GET", "/api/state"),
                         ("DELETE", "/api/integrations"), ("POST", "/api/golemfm/status"), ("POST", "/api/t3k/auth/status"),
                         ("GET", "/api/integrations/../system/update")):
        with pytest.raises(PermissionError):
            m._bridge(method, path)


def test_seules_la_cle_le_jeton_et_le_serveur_s_ecrivent(monkeypatch):
    m = _server()
    m.S["dry"] = False
    sent = []

    class R:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": true}'

    def fake(req, timeout=None):
        sent.append((req.full_url, req.get_method(), json.loads(req.data)))
        return R()
    monkeypatch.setattr(urllib.request, "urlopen", fake)
    m._bridge("POST", "/api/integrations", {"golemfm": {"token": "t", "base_url": "https://x", "auto_push": True},
                                            "tone3000": {"publishable_key": "k", "T3K_ACCESS_TOKEN": "z"},
                                            "unknown_section": {"evil": 1}})
    assert sent == [("http://127.0.0.1:8770/api/integrations", "POST",
                     {"golemfm": {"base_url": "https://x", "token": "t"}, "tone3000": {"publishable_key": "k"}})]


def test_en_dry_le_parcours_complet_ne_touche_jamais_8770(no_bridge):
    m = _server()
    m.S.update(dry=True, src=ROOT)
    st = m.link_state()
    assert st["up"] and st["dry"] and not st["golemfm"]["authed"] and not st["t3k"]["key"]["set"]
    # golem.fm : le serveur vient du .env du golem (GOLEM_SERVER_URL) — l'appairage donne le code
    p = m.link_pair()
    assert p["ok"] and p["code"] and p["approve_url"].endswith(p["code"])
    assert m.link_pair_status()["active"] and m.link_pair_status()["active"]
    assert m.link_pair_status() == {"active": False, "approved": True}
    st = m.link_state()
    assert st["golemfm"]["authed"] and st["golemfm"]["band"] and st["golemfm"]["server"]["host"]
    # TONE3000 : appairé à golem.fm, la connexion passe par le relais SANS clé (pas d'adresse de retour à déclarer) ;
    # la clé à soi reste possible (une refusée se dit, la bonne passe) ; la connexion aboutit ; le téléchargement avance
    s = m.link_t3k_signin()
    assert s["ok"] and s["auth_url"].startswith("https://") and not s.get("redirect_uri")
    assert m.link_t3k_key({"key": "abc"})["ok"] is False
    assert m.link_t3k_key({"key": "pk_dry_1234abcd"}) == {"ok": True}
    while not m.link_t3k_status()["authed"]:
        pass
    assert m._bridge("POST", "/api/factory/captures/download")["ok"]
    for _ in range(10):
        f = m.link_factory()
        if f["download"]["phase"] == "done":
            break
    assert f["download"]["phase"] == "done" and f["missing"] == 1 and f["download"]["failed"]
    # le jeton collé à la main passe par la même route
    assert m.link_token({"token": "abc"}) == {"ok": True}
    assert no_bridge == []
    # le chemin Windows/macOS (factory_start) aussi, sans lancer golem ni ouvrir de navigateur
    m.DB.reset()
    m.DB.call("POST", "/api/integrations", {"tone3000": {"publishable_key": "pk_dry_1234abcd"}})
    assert m.factory_start()["step"] == "signin"
    assert no_bridge == []


def test_en_dry_golem_eteint_se_dit_sans_requete(no_bridge, monkeypatch):
    m = _server()
    m.S["dry"] = True
    monkeypatch.setenv("GOLEM_INSTALLER_DRY_BRIDGE", "down")
    assert m.link_state() == {"up": False, "dry": True}
    assert m.link_pair()["down"] and m.link_t3k_signin()["down"]
    assert m.factory_state() == {"up": False}
    assert no_bridge == []


def test_les_routes_http_de_l_ecran_en_dry(no_bridge, monkeypatch):
    """Par le vrai serveur HTTP : jeton exigé, aucun corps relayé tel quel, aucun navigateur ouvert en --dry."""
    m = _server()
    m.S.update(dry=True, src=ROOT)
    opened = []
    monkeypatch.setattr(m.P, "open_url", lambda url: opened.append(url))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), m.H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        def call(method, path, body=None, token=True):
            c = http.client.HTTPConnection("127.0.0.1", srv.server_address[1], timeout=10)
            h = {"Content-Type": "application/json", **({"X-Golem-Token": m.S["token"]} if token else {})}
            c.request(method, path, body=json.dumps(body) if body is not None else None, headers=h)
            r = c.getresponse()
            return r.status, json.loads(r.read() or b"{}")
        assert call("GET", "/api/link", token=False)[0] == 403
        assert call("GET", "/api/link")[1]["up"] is True
        assert call("POST", "/api/link/pair", {})[1]["ok"] is True
        assert call("POST", "/api/link/t3k-key", {"key": "pk_dry_1234abcd"})[1] == {"ok": True}
        assert call("POST", "/api/link/t3k-signin", {})[1]["ok"] is True
        assert call("POST", "/api/open", {"url": "https://golem.fm.example/devices"})[1]["ok"] is True
        assert call("GET", "/api/link/factory")[1]["up"] is True
        # pas de relais générique : une route qui n'est pas un geste de l'écran n'existe pas
        assert call("POST", "/api/link/raw", {"path": "/api/system/update"})[0] == 404
    finally:
        srv.shutdown()
    assert opened == [] and no_bridge == []


def test_linux_n_affiche_plus_l_app_dans_un_cadre():
    js = open(os.path.join(ROOT, "installer", "ui", "installer.js"), encoding="utf-8").read()
    assert "<iframe" not in js and "#/system/api" not in js
    assert "new Image()" not in js                      # l'ancienne sonde de :8770 depuis la page
    # la page ne parle qu'à son serveur : aucun fetch vers :8770 (le seul :8770 restant = l'adresse affichée/ouverte à la fin)
    assert "fetch('http" not in js and 'fetch("http' not in js
    assert "ConnectLive" in js and "/api/link" in js
