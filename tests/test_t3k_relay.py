# SPDX-License-Identifier: GPL-3.0-or-later
"""Le relais TONE3000 de golem.fm (2026-10-22) : un golem appairé se connecte sans clé ni adresse à déclarer. Il garde son
PKCE et fait l'échange lui-même, avec le client_id et le redirect_uri RENDUS — et la lignée se rafraîchit avec ce client."""
import asyncio

import pytest

from bridge import golemfm, routes_t3k

t3k = routes_t3k._t3k                  # l'exemplaire de tools/t3k.py que le bridge charge (importlib)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(t3k, "ENV", str(tmp_path / ".env"))
    monkeypatch.setattr(t3k, "LOCK", str(tmp_path / "token.lock"))
    monkeypatch.setattr(routes_t3k, "_RELAY_POLL_S", 0)
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://golem.example", "dev-token"))
    routes_t3k._RELAY.update(state=None, error=None, running=False)
    return tmp_path


def _replies(monkeypatch, seq):
    calls = []

    def fake(path, body=None, token=None, base=None, timeout=None, raw=False, method=None):
        calls.append((path, body, token))
        return seq.pop(0) if len(seq) > 1 else seq[0]
    monkeypatch.setattr(golemfm, "_req", fake)
    return calls


def test_le_relais_rend_un_code_et_le_golem_fait_l_echange_avec_le_client_rendu(env, monkeypatch):
    calls = _replies(monkeypatch, [(202, {"status": "pending"}), (200, {"status": "ready", "code": "C0DE",
                                    "client_id": "t3k_pub_golemfm", "redirect_uri": "https://golem.example/api/golem/t3k/callback"})])
    sent = {}

    def token(data):
        sent.update(data)
        t3k.env_set({"T3K_ACCESS_TOKEN": "a", "T3K_REFRESH_TOKEN": "r", "T3K_TOKEN_CLIENT": data["client_id"]})
    monkeypatch.setattr(t3k, "token_request", token)
    routes_t3k._RELAY.update(state="g.abc", running=True)
    routes_t3k._relay_poll("g.abc", "VERIFIER")
    assert calls[0][0] == "/api/ext/t3k/relay/g.abc" and calls[0][2] == "dev-token"
    assert sent == {"grant_type": "authorization_code", "code": "C0DE", "client_id": "t3k_pub_golemfm",
                    "redirect_uri": "https://golem.example/api/golem/t3k/callback", "code_verifier": "VERIFIER"}
    assert routes_t3k._RELAY == {"state": "g.abc", "error": None, "running": False}
    assert t3k.client_id() == "t3k_pub_golemfm"            # la lignée se rafraîchira avec le client qui l'a ouverte


@pytest.mark.parametrize("reply, said", [((200, {"status": "denied"}), "refused"), ((410, {"detail": {"error": "expired"}}), "expired")])
def test_refuse_ou_expire_se_dit_sans_echange(env, monkeypatch, reply, said):
    _replies(monkeypatch, [reply])
    monkeypatch.setattr(t3k, "token_request", lambda data: pytest.fail("no exchange without a code"))
    routes_t3k._RELAY.update(state="g.x", running=True)
    routes_t3k._relay_poll("g.x", "V")
    assert said in routes_t3k._RELAY["error"] and routes_t3k._RELAY["running"] is False


def test_demarrer_un_golem_appaire_passe_par_le_relais_avec_le_challenge_s256(env, monkeypatch):
    calls = _replies(monkeypatch, [(200, {"state": "g.s", "authorize_url": "https://www.tone3000.com/authorize?x=1",
                                         "client_id": "t3k_pub_golemfm", "redirect_uri": "https://golem.example/cb", "expires_in": 600})])
    monkeypatch.setattr(routes_t3k, "_relay_poll", lambda state, verifier: None)
    out = asyncio.run(routes_t3k.t3k_auth_start())
    assert out["relay"] is True and out["auth_url"].startswith("https://www.tone3000.com/") and out["qr"]
    path, body, token = calls[0]
    assert path == "/api/ext/t3k/relay" and token == "dev-token" and len(body["challenge"]) == 43


def test_sans_golem_fm_c_est_la_cle_a_soi(env, monkeypatch):
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("", ""))
    t3k.env_set({"T3K_PUBLISHABLE_KEY": "t3k_pub_mine"})
    out = asyncio.run(routes_t3k.t3k_auth_start())
    assert out["relay"] is False and "client_id=t3k_pub_mine" in out["auth_url"] and out["redirect_uri"]
