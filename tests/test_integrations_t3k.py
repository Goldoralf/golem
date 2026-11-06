# SPDX-License-Identifier: GPL-3.0-or-later
"""2026-09-13 (retour golem.fm) : un jeton TONE3000 a UN propriétaire et UN magasin (.env).

integrations.json semait un instantané périmé des jetons (nom et forme du vrai, jamais rafraîchi),
et Settings ▸ API laissait en coller un — deux machines sur une lignée = famille révoquée.
"""
import json
from types import SimpleNamespace as NS
from bridge import routes_content as RC


class _Env:
    def __init__(self): self.d = {"T3K_PUBLISHABLE_KEY": "t3k_pub_abc"}
    def env_read(self): return dict(self.d)
    def env_set(self, u): self.d.update(u)
    def own_key(self): return self.d.get("T3K_PUBLISHABLE_KEY", "")


def test_le_reliquat_est_purge_a_la_lecture(tmp_path, monkeypatch):
    path = tmp_path / "integrations.json"
    json.dump({"tone3000": {"access_token": "old", "refresh_token": "dead", "publishable_key": "stale"},
               "golemfm": {"base_url": "https://golem.fm", "token": "m"}}, open(path, "w"))
    monkeypatch.setattr(RC, "_INTEGRATIONS_PATH", str(path))
    monkeypatch.delenv("GOLEM_SERVER_URL", raising=False)          # le .env d'un poste de dev ne compte pas
    env = _Env(); monkeypatch.setattr(RC, "_t3k_env", lambda: env)
    d = RC._load_integrations()
    assert d["tone3000"] == {"publishable_key": "t3k_pub_abc"}          # la clé vient de .env, rien d'autre
    assert d["golemfm"]["token"] == "m"
    on_disk = json.load(open(path))
    assert "access_token" not in on_disk["tone3000"] and "refresh_token" not in on_disk["tone3000"]   # purgé


def test_on_ne_colle_jamais_un_jeton(tmp_path, monkeypatch):
    import asyncio
    monkeypatch.setattr(RC, "_INTEGRATIONS_PATH", str(tmp_path / "i.json"))
    env = _Env(); monkeypatch.setattr(RC, "_t3k_env", lambda: env)
    r = asyncio.run(RC.save_integrations({"tone3000": {"refresh_token": "pasted"}}))
    assert r.status_code == 400 and b"never pasted" in r.body
    r = asyncio.run(RC.save_integrations({"tone3000": {"publishable_key": "t3k_pub_new"}}))
    assert r == {"ok": True} and env.d["T3K_PUBLISHABLE_KEY"] == "t3k_pub_new"     # la clé va dans .env
    assert json.load(open(tmp_path / "i.json"))["tone3000"] == {}                # rien de TONE3000 sur disque


def test_l_exemple_de_env_example_n_est_pas_une_cle(tmp_path, monkeypatch):
    # install.sh copie .env.example : « t3k_pub_colle_ta_cle_ici » faisait dire « key saved » à un golem neuf (VM 2026-10-23)
    import importlib.util
    import os
    spec = importlib.util.spec_from_file_location("t3k_tool", os.path.join(os.path.dirname(__file__), "..", "tools", "t3k.py"))
    t3k = importlib.util.module_from_spec(spec); spec.loader.exec_module(t3k)
    env = tmp_path / ".env"
    monkeypatch.setattr(t3k, "ENV", str(env))
    env.write_text("T3K_PUBLISHABLE_KEY=t3k_pub_colle_ta_cle_ici\n")
    assert t3k.own_key() == ""
    env.write_text("T3K_PUBLISHABLE_KEY=t3k_pub_AbC123\n")
    assert t3k.own_key() == "t3k_pub_AbC123"
    assert "colle_ta_cle" not in open(os.path.join(os.path.dirname(__file__), "..", ".env.example"), encoding="utf-8").read()
