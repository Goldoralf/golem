# SPDX-License-Identifier: GPL-3.0-or-later
"""Les comptes avant l'installation (installer/early.py, docs/install-v2.md lots 4-5) : l'aller-retour golem.fm, le
relais TONE3000, des jetons qui ne sortent jamais par l'écran, et les captures téléchargées hors de golem."""
import importlib.util
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "installer"))
spec = importlib.util.spec_from_file_location("golem_installer_early", ROOT / "installer" / "early.py")
EA = importlib.util.module_from_spec(spec)
spec.loader.exec_module(EA)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    EA.reset()
    monkeypatch.setattr(EA, "POLL_S", 0.01)
    monkeypatch.setitem(EA.DRY, "on", False)
    monkeypatch.delenv("GOLEM_SERVER_URL", raising=False)
    yield
    EA.reset()


def _wait(pred, secs=3.0):
    t0 = time.time()
    while time.time() - t0 < secs:
        if pred():
            return True
        time.sleep(0.01)
    return False


def test_l_adresse_de_retour_ne_porte_aucun_jeton():
    u = EA.with_return("https://golem.fm/pair?code=ABC-DEF", 43210)
    assert u == "https://golem.fm/pair?code=ABC-DEF&return_to=http%3A%2F%2F127.0.0.1%3A43210%2Fback"
    assert EA.with_return("https://golem.fm/pair", 1).startswith("https://golem.fm/pair?return_to=")


def test_l_appairage_part_sonde_et_garde_le_jeton_hors_de_l_ecran(monkeypatch):
    calls = []

    def http(method, path, body=None, token=None, timeout=8):
        calls.append((method, path, body, token))
        if path == "/api/ext/pair/start":
            return 200, {"code": "ABC-DEF", "poll_token": "pt", "approve_url": "https://golem.fm/pair?code=ABC-DEF", "expires_in": 1200}
        n = sum(1 for c in calls if c[1] == "/api/ext/pair/poll")
        return (200, {"status": "approved", "token": "SECRET-DEVICE-TOKEN", "name": "Studio"}) if n >= 3 else (200, {"status": "pending"})
    monkeypatch.setattr(EA, "_http", http)
    st = EA.pair_start(str(ROOT), 5555, device_name="golem")
    assert st["pair"]["phase"] == "waiting" and st["pair"]["code"] == "ABC-DEF" and "poll_token" not in st["pair"]
    assert "return_to=http%3A%2F%2F127.0.0.1%3A5555%2Fback" in st["pair"]["approve_url"]
    start = calls[0]
    assert start[2]["device_name"] == "golem" and start[2]["rack"]["installer"] == "gui" and start[3] is None
    assert _wait(lambda: EA.state()["paired"])
    s = EA.state()
    assert s["pair"] == {"phase": "paired", "name": "Studio"} and "SECRET" not in repr(s)      # le jeton ne sort jamais
    assert EA.golem_token() == "SECRET-DEVICE-TOKEN"


def test_un_code_mort_ou_golem_fm_injoignable_se_disent(monkeypatch):
    monkeypatch.setattr(EA, "_http", lambda *a, **k: (0, None))
    assert "not reachable" in EA.pair_start(str(ROOT), 1)["pair"]["error"]
    seq = iter([(200, {"code": "X", "poll_token": "pt", "approve_url": "u"}), (409, None)])
    monkeypatch.setattr(EA, "_http", lambda *a, **k: next(seq))
    EA.pair_start(str(ROOT), 1)
    assert _wait(lambda: EA.state()["pair"]["phase"] == "expired") and EA.state()["pair"]["error"] == "already claimed"
    assert not EA.state()["paired"]


def test_tone3000_demande_l_appairage_puis_passe_par_le_relais(monkeypatch, tmp_path):
    assert "pair with golem.fm first" in EA.t3k_start(str(ROOT))["t3k"]["error"]
    EA._S["token"] = "DEV"
    seen = {}

    class FakeT3k:
        def __init__(self, env):
            self.env = env

        def pkce(self):
            return "verifier", "challenge"

        def token_request(self, data):
            seen["exchange"] = data
            open(self.env, "w").write("T3K_ACCESS_TOKEN=acc\nT3K_REFRESH_TOKEN=ref\nT3K_TOKEN_CLIENT=cid\nOTHER=x\n")

        def env_read(self):
            return dict(line.split("=", 1) for line in open(self.env).read().split())
    monkeypatch.setattr(EA, "_t3k_module", lambda src, env_path: seen.setdefault("mod", FakeT3k(env_path)))

    def http(method, path, body=None, token=None, timeout=8):
        assert token == "DEV"                                                    # le jeton d'appareil, rien d'autre
        if method == "POST":
            assert body == {"challenge": "challenge"}                             # le verifier reste ici
            return 200, {"authorize_url": "https://www.tone3000.com/authorize?x", "state": "st1"}
        return 200, {"status": "ready", "code": "C", "client_id": "cid", "redirect_uri": "https://golem.fm/t3k/cb"}
    monkeypatch.setattr(EA, "_http", http)
    st = EA.t3k_start(str(ROOT))
    assert st["t3k"]["phase"] == "waiting" and st["t3k"]["auth_url"].startswith("https://www.tone3000.com/")
    assert _wait(lambda: EA.state()["t3k_signed_in"])
    assert seen["exchange"] == {"grant_type": "authorization_code", "code": "C", "redirect_uri": "https://golem.fm/t3k/cb",
                                "client_id": "cid", "code_verifier": "verifier"}
    assert EA._S["t3k_env"] == {"T3K_ACCESS_TOKEN": "acc", "T3K_REFRESH_TOKEN": "ref", "T3K_TOKEN_CLIENT": "cid"}
    assert "acc" not in repr(EA.state()) and not os.path.exists(seen["mod"].env)   # ni à l'écran, ni resté sur le disque
    # … puis dans le .env du dossier installé, par son propre tools/t3k.py
    target = tmp_path / "golem"
    (target / "tools").mkdir(parents=True)
    (target / "tools" / "t3k.py").write_text((ROOT / "tools" / "t3k.py").read_text(encoding="utf-8"), encoding="utf-8")
    assert EA.apply_env(str(target)) is True
    env = (target / ".env").read_text()
    assert "T3K_ACCESS_TOKEN=acc" in env and "T3K_REFRESH_TOKEN=ref" in env and oct((target / ".env").stat().st_mode & 0o777) == "0o600"


def test_a_blanc_rien_ne_part_et_tout_se_joue(monkeypatch):
    monkeypatch.setitem(EA.DRY, "on", True)
    monkeypatch.setattr(EA, "_http", lambda *a, **k: (_ for _ in ()).throw(AssertionError("a request left in --dry")))
    EA.pair_start(str(ROOT), 1)
    assert _wait(lambda: EA.state()["paired"])
    EA.t3k_start(str(ROOT))
    assert _wait(lambda: EA.state()["t3k_signed_in"], 5)
    assert EA.apply_env("/nonexistent") is False                                  # à blanc : rien n'est écrit


def test_les_captures_se_telechargent_hors_de_golem(tmp_path, monkeypatch):
    """bridge/factory_fetch.py : pas de compte -> 2 et rien ; un compte -> le travail de Settings ▸ Factory, suivi sur disque."""
    import json
    from bridge import factory as F
    from bridge import factory_fetch as FF
    from bridge import routes_t3k as T
    from bridge import config as C
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(T._t3k, "env_read", lambda: {})
    assert FF.run(tick=0.01) == 2 and json.load(open(FF.status_path()))["phase"] == "skipped"
    monkeypatch.setattr(T._t3k, "env_read", lambda: {"T3K_ACCESS_TOKEN": "x"})
    monkeypatch.setattr(F, "captures", lambda: {"missing": [{"tone": 1, "title": "A"}, {"tone": 2, "title": "B"}]})

    def worker(todo):
        for i, it in enumerate(todo):
            (F._DL["installed"] if it["tone"] == 1 else F._DL["failed"]).append(it["tone"] if it["tone"] == 1 else {"tone": 2, "why": "x"})
            F._DL.update(done=i + 1)
        F._DL.update(phase="done")
    monkeypatch.setattr(F, "_download_worker", worker)
    assert FF.run(tick=0.01) == 1                                                 # une en échec : dit par le code de sortie
    d = json.load(open(FF.status_path()))
    assert d["phase"] == "done" and d["done"] == 2 and d["total"] == 2 and d["failed"] == [{"tone": 2, "why": "x"}]
    monkeypatch.setattr(F, "captures", lambda: {"missing": []})
    assert FF.run(tick=0.01) == 0
