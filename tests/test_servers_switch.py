# SPDX-License-Identifier: GPL-3.0-or-later
"""Le serveur golem.fm vient de .env (Alex, 2026-10-31 : plus de menu Advanced). GOLEM_SERVER_URL, golem.fm par
défaut. Ce que ces tests gardent : chaque serveur garde son jeton ; changer la variable ne présente jamais le jeton
d'un serveur à l'autre ; l'écran ne peut pas changer de serveur ; il ne voit aucun jeton."""
import json

import pytest

from bridge import golemfm, routes_content as RC

PROD, LOCAL = "https://golem.fm", "http://localhost:5173"


@pytest.fixture
def integ(tmp_path, monkeypatch):
    p = tmp_path / "integrations.json"
    json.dump({"golemfm": {"base_url": PROD, "token": "gmt_prod"}}, open(p, "w"))
    monkeypatch.setattr(RC, "_INTEGRATIONS_PATH", str(p))
    monkeypatch.setattr(RC, "_t3k_env", lambda: type("E", (), {"env_read": lambda s: {}, "own_key": lambda s: "", "env_set": lambda s, d: None})())
    monkeypatch.delenv("GOLEM_SERVER_URL", raising=False)
    return p


def _save(body):
    import asyncio
    return asyncio.run(RC.save_integrations(body))


def test_sans_variable_c_est_golem_fm(integ):
    assert RC.server_url() == PROD
    m = RC._load_integrations()["golemfm"]
    assert m["base_url"] == PROD and m["token"] == "gmt_prod"


def test_changer_la_variable_garde_le_jeton_de_chaque_serveur(integ, monkeypatch):
    monkeypatch.setenv("GOLEM_SERVER_URL", LOCAL + "/")
    m = RC._load_integrations()["golemfm"]
    assert m["base_url"] == LOCAL and m["token"] == ""                   # jamais le jeton de la prod au local
    golemfm._save_token("gmt_local")                                    # appairage du local
    monkeypatch.delenv("GOLEM_SERVER_URL")
    m = RC._load_integrations()["golemfm"]
    assert m["base_url"] == PROD and m["token"] == "gmt_prod"             # la prod revient avec SON jeton
    monkeypatch.setenv("GOLEM_SERVER_URL", LOCAL)
    assert RC._load_integrations()["golemfm"]["token"] == "gmt_local"   # et le local avec le sien


def test_l_ecran_ne_change_pas_de_serveur(integ):
    r = _save({"golemfm": {"base_url": LOCAL}})
    assert r.status_code == 400 and b"GOLEM_SERVER_URL" in r.body
    assert _save({"golemfm": {"base_url": PROD + "/", "auto_push": True}}) == {"ok": True}   # le même : accepté


def test_lecran_ne_voit_aucun_jeton(integ):
    got = RC.get_integrations()["golemfm"]
    assert got["base_url"] == PROD and got["token"]["set"] and "servers" not in got
    assert "gmt_prod" not in json.dumps(got)


def test_un_serveur_en_clair_hors_du_reseau_local_vaut_non_configure(integ, monkeypatch):
    monkeypatch.setenv("GOLEM_SERVER_URL", "http://golem.fm.evil.test")
    assert golemfm._cfg() == ("", "")
