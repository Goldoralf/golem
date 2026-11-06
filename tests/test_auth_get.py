# SPDX-License-Identifier: GPL-3.0-or-later
"""AUDIT 2026-09-13, M3 : l'état du rack ne se lit pas sans jeton depuis le LAN.

/api/state porte les prénoms du roster ; un appareil jamais appairé le lisait en GET (200 mesuré).
Le kiosk (localhost) et les appareils appairés (cookie) ne changent pas.
"""
from types import SimpleNamespace as NS
from bridge import auth


def _req(path, host="192.168.0.50", method="GET", token=""):
    return NS(method=method, url=NS(path=path, hostname="192.168.0.22"), client=NS(host=host),
              headers={"x-golem-token": token} if token else {}, cookies={}, query_params={})


def test_letat_du_rack_exige_un_jeton_depuis_le_lan(monkeypatch):
    monkeypatch.setattr(auth, "_device_by_token", lambda t: {"id": "d1"} if t == "ok" else None)
    for path in ("/api/state", "/api/sandbox", "/api/presets", "/api/preset/velvetine", "/api/patches",
                 "/api/modes", "/api/inputmap", "/api/setlists"):
        assert auth.allowed_http(_req(path)) is False, path                 # LAN, sans jeton
        assert auth.allowed_http(_req(path, token="ok")) is True, path      # LAN, appareil appairé
        assert auth.allowed_http(_req(path, host="127.0.0.1")) is True, path   # le kiosk


def test_ce_qui_reste_ouvert_le_reste():
    """L'app statique et sa version : un téléphone doit pouvoir CHARGER la page avant de s'appairer."""
    for path in ("/api/app-build", "/api/health", "/api/effects"):
        assert auth.allowed_http(_req(path)) is True, path


def test_le_jeton_en_query_ne_vaut_rien_en_http(monkeypatch):
    """m3 : `?token=` finit dans l'historique et les journaux — header ou cookie seulement."""
    monkeypatch.setattr(auth, "_device_by_token", lambda t: {"id": "d1"} if t == "ok" else None)
    r = _req("/api/state"); r.query_params = {"token": "ok"}
    assert auth.allowed_http(r) is False


def test_une_autre_appli_web_de_la_machine_nest_pas_lecran_local():
    """Revue 2026-10-25 : l'Origin d'un autre port de la machine (un serveur de dev sur localhost:5173) passait pour
    l'écran local, admin — un POST sans corps n'a pas de preflight. Le port de l'Origin doit être celui du bridge."""
    def post(origin):
        return NS(method="POST", url=NS(path="/api/system/bridge-restart", hostname="localhost", port=8770, scheme="http"),
                  client=NS(host="127.0.0.1"), headers={"origin": origin}, cookies={}, query_params={})
    assert auth.allowed_http(post("http://localhost:8770")) is True
    assert auth.allowed_http(post("http://127.0.0.1:8770")) is True
    assert auth.allowed_http(post("http://localhost:5173")) is False
    assert auth.allowed_http(post("http://localhost")) is False


def test_un_jeton_non_ascii_est_refuse_pas_un_500():
    """Revue 2026-10-25 : compare_digest sur deux str lève TypeError au premier caractère non ASCII."""
    assert auth._device_by_token("é") is None
    assert auth.allowed_http(_req("/api/state", token="é")) is False
    assert auth._same(None, "None") is False and auth._same("", "") is False and auth._same("a", "a") is True
