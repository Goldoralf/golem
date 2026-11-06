# SPDX-License-Identifier: GPL-3.0-or-later
"""Desktop OAuth callback and token lock use native host behavior."""
import os

from bridge import routes_t3k
from tools import t3k


def test_desktop_oauth_callback_stays_on_loopback(monkeypatch):
    monkeypatch.setenv("GOLEM_PORT", "8870")
    monkeypatch.setattr(routes_t3k.sys, "platform", "win32")
    assert routes_t3k._redirect_uri() == "http://127.0.0.1:8870/api/t3k/auth/callback"
    monkeypatch.setattr(routes_t3k.sys, "platform", "darwin")
    assert routes_t3k._redirect_uri() == "http://127.0.0.1:8870/api/t3k/auth/callback"
    monkeypatch.setattr(routes_t3k.sys, "platform", "linux")
    monkeypatch.setattr(routes_t3k, "_lan_ip", lambda: "192.0.2.10")
    assert routes_t3k._redirect_uri() == "http://192.0.2.10:8870/api/t3k/auth/callback"


def test_token_lock_is_released(tmp_path, monkeypatch):
    monkeypatch.setattr(t3k, "LOCK", str(tmp_path / "token.lock"))
    with t3k._env_lock() as lock:
        assert os.path.exists(t3k.LOCK)
        assert os.fstat(lock.fd)
    try:
        os.fstat(lock.fd)
    except OSError:
        pass
    else:
        raise AssertionError("token lock descriptor still open")
