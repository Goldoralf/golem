# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit de publication du 2026-11-04 (docs/private/audit-2026-11-04-publication.md §1) : les quatre High du bridge
et la passe sur les paliers."""
import logging
import os

import pytest

from bridge import auth, importer, resolver, scrub
from bridge import config as C
from tests.test_audit_2026_10_15_security import Req, DEVS


@pytest.fixture
def devs(monkeypatch):
    monkeypatch.setattr(auth, "_device_by_token", lambda t: DEVS.get(t))


# ── H1 : un catalogue importé ne mène pas hors d'assets/ ──────────────────────────────────────────────────────────
def test_h1_import_est_un_geste_dadmin(devs):
    for path in ("/api/import/inspect", "/api/import/apply", "/api/import/inspect-local"):
        assert auth.allowed_http(Req("POST", path, "guest")) is False
        assert auth.allowed_http(Req("POST", path, "musician")) is False
        assert auth.allowed_http(Req("POST", path, "admin")) is True


def test_h1_un_fichier_du_catalogue_vit_sous_assets():
    assert resolver._asset_path("config/auth-devices.json") is None
    assert resolver._asset_path(".env") is None
    assert resolver._asset_path("assets/../config/auth-devices.json") is None
    assert resolver._asset_path("assets/amps/x.nam") == os.path.realpath(os.path.join(C.ROOT, "assets", "amps", "x.nam"))


def test_h1_une_entree_importee_hors_assets_est_ecartee(tmp_path, monkeypatch):
    cat = tmp_path / "tones-index.json"
    monkeypatch.setattr(C, "CATALOG", str(cat))
    bad = [{"id": "a", "parametric": {"file": "config/auth-devices.json"}, "models": [{"file": "assets/x.nam"}]},
           {"id": "b", "models": [{"file": "/etc/passwd"}]},
           {"id": "c", "models": [{"file": "assets/../.env"}]},
           {"id": "d", "file": "C:\\Users\\x\\.env"}]
    good = {"id": "ok", "models": [{"file": "assets/amps/ok.nam"}]}
    assert importer._merge_catalog(bad + [good], "overwrite") == 1
    import json
    assert [t["id"] for t in json.loads(cat.read_text())["tones"]] == ["ok"]


# ── H2 : le jeton d'appareil ne sort pas dans un journal ──────────────────────────────────────────────────────────
def test_h2_le_scrubber_efface_un_jeton_dappareil():
    import secrets
    tok = secrets.token_urlsafe(32)
    line = f'127.0.0.1:5555 - "WebSocket /ws?token={tok}" [accepted]'
    out = scrub.RX_TOKEN.sub("<token>", line)
    assert tok not in out
    assert "WebSocket /ws" in out


def test_h2_uvicorn_ne_journalise_plus_la_query_du_websocket():
    import bridge.app  # noqa: F401 — pose le filtre sur les journaux d'uvicorn
    rec = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, '%s - "WebSocket %s" [accepted]',
                            (("127.0.0.1", 5555), "/ws?token=abcDEF_123-xyz"), None)
    for f in logging.getLogger("uvicorn.error").filters:
        f.filter(rec)
    assert "abcDEF_123-xyz" not in rec.getMessage()
    assert "token=<token>" in rec.getMessage()


def test_h2_le_paquet_de_diagnostic_est_admin(devs):
    assert auth.allowed_http(Req("POST", "/api/diag/build", "musician")) is False
    assert auth.allowed_http(Req("GET", "/api/diag/r1/download", "musician")) is False
    assert auth.allowed_http(Req("GET", "/api/diag/r1/download", "admin")) is True


# ── H3 : l'appairage golem.fm ─────────────────────────────────────────────────────────────────────────────────────
def test_h3_appairage_golemfm_ni_public_ni_membre(devs):
    assert auth.allowed_http(Req("GET", "/api/golemfm/pair/status")) is False
    assert auth.allowed_http(Req("GET", "/api/golemfm/pair/status", "musician")) is False
    assert auth.allowed_http(Req("POST", "/api/golemfm/pair", "musician")) is False
    assert auth.allowed_http(Req("POST", "/api/golemfm/pair", "admin")) is True


# ── H4 : le retour de connexion TONE3000 n'interprète pas l'URL ───────────────────────────────────────────────────
def test_h4_callback_tone3000_echappe_lerreur():
    from bridge import routes_t3k
    r = routes_t3k.t3k_auth_callback(error="<svg onload=alert(1)>")
    body = r.body.decode()
    assert "<svg" not in body and "&lt;svg" in body


# ── M1, M3, L1 : les GET que le palier admin ne voyait pas ────────────────────────────────────────────────────────
def test_m3_les_lectures_admin_le_sont_vraiment(devs):
    for path in ("/api/integrations", "/api/system/update", "/api/system/reaper-update", "/api/auth/qr"):
        assert auth.allowed_http(Req("GET", path)) is False, path
        assert auth.allowed_http(Req("GET", path, "musician")) is False, path
        assert auth.allowed_http(Req("GET", path, "admin")) is True, path


def test_m1_le_systeme_de_fichiers_ne_se_parcourt_pas_depuis_le_lan(devs):
    for path in ("/api/kits/import/browse", "/api/kits/import/volumes", "/api/song-folders/browse"):
        assert auth.allowed_http(Req("GET", path)) is False, path
        assert auth.allowed_http(Req("GET", path, "musician")) is False, path
        assert auth.allowed_http(Req("GET", path, "admin")) is True, path
    for path in ("/api/song-folders", "/api/inbox", "/api/storage"):
        assert auth.allowed_http(Req("GET", path)) is False, path
        assert auth.allowed_http(Req("GET", path, "musician")) is True, path


def test_m5_le_mot_de_passe_ne_traverse_pas_le_wifi():
    import asyncio
    import json
    from bridge import routes_machine
    remote = type("Req", (), {"client": type("C", (), {"host": "192.168.0.25"})()})()
    r = asyncio.run(routes_machine.harden_post(remote, {"password": "x"}))
    assert r.status_code == 403
    assert "own screen" in json.loads(r.body)["error"]


def test_m6_seuls_les_noms_local_du_rack_passent(monkeypatch):
    import socket
    monkeypatch.setattr(socket, "gethostname", lambda: "studiopc")
    for h in ("golem.local:8770", "golem-studiopc.local", "studiopc.local", "studiopc", "localhost", "192.168.0.22:8770"):
        assert auth.host_ok(h) is True, h
    for h in ("evil.local", "evil.local:8770", "golem.local.evil.com", "attacker.example"):
        assert auth.host_ok(h) is False, h


def test_m9_un_corps_trop_gros_sarrete_au_plafond():
    import asyncio
    from bridge.http_body import read_body, TooLarge

    class R:
        def __init__(self, chunks, declared=None):
            self.headers = {"content-length": str(declared)} if declared else {}
            self._chunks, self.read = chunks, 0

        async def stream(self):
            for c in self._chunks:
                self.read += 1
                yield c

    r = R([b"x" * 1000] * 100)
    with pytest.raises(TooLarge):
        asyncio.run(read_body(r, 5000))
    assert r.read == 6                                     # s'est arrêté au plafond, n'a pas tout lu
    big = R([b"x"], declared=10 ** 10)
    with pytest.raises(TooLarge):
        asyncio.run(read_body(big, 5000))
    assert big.read == 0                                   # Content-Length trop grand : rien lu
    assert asyncio.run(read_body(R([b"ab", b"cd"]), 5000)) == b"abcd"


def test_m4_un_appareil_jamais_appaire_ne_lit_rien_de_lapi(devs):
    for path in ("/api/live/lyrics", "/api/foot-list", "/api/fcb-banks", "/api/devices", "/api/lane/mine",
                 "/api/backing/catalog", "/api/network/status", "/api/system", "/api/une-route-de-demain"):
        assert auth.allowed_http(Req("GET", path)) is False, path                       # LAN, sans jeton
        assert auth.allowed_http(Req("GET", path, "guest")) is True, path               # appairé : comme avant
        assert auth.allowed_http(Req("GET", path, client="127.0.0.1", host="localhost:8770")) is True, path
    # de quoi charger l'app et apprendre qu'il faut s'appairer, le pouls du lanceur, le retour TONE3000, l'app statique
    for path in ("/api/auth/whoami", "/api/health", "/api/app-build", "/api/effects", "/api/t3k/auth/callback",
                 "/api/auth/pair", "/app/index.html", "/library/catalog/x.png"):
        assert auth.allowed_http(Req("GET", path)) is True, path
    assert auth.allowed_http(Req("GET", "/api/state", "jeton-inconnu")) is False


def test_le_rack_lui_meme_reste_admin():
    for path in ("/api/import/apply", "/api/golemfm/pair", "/api/diag/build"):
        assert auth.allowed_http(Req("POST", path, client="127.0.0.1", host="localhost:8770")) is True
