# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit du 2026-10-15, lot 4 : Origin du WebSocket, corps d'erreur de golem.fm, règle https à la LECTURE,
ids de job pris pour des ids de mode/pack, marque."""
import io
import json
import urllib.error

import pytest

from bridge import auth, connect, golemfm, tones_jobs, tones_sync
from bridge import routes_content as RC

_REAL_CFG = golemfm._cfg          # conftest le remplace (aucun test ne parle au vrai serveur) : c'est lui qu'on teste


@pytest.fixture
def real_cfg(monkeypatch):
    """Le vrai _cfg, sur une config SIMULÉE (jamais integrations.json) et sans réseau."""
    monkeypatch.setattr(golemfm, "_cfg", _REAL_CFG)
    monkeypatch.setattr(golemfm.urllib.request, "urlopen", lambda *a, **k: pytest.fail("network"))


# ── (a) WebSocket : même règle Origin que le HTTP, client local compris ──────────────────────────
class WS:
    def __init__(self, client="127.0.0.1", host="localhost:8770", origin=None, token=""):
        self.headers = {"host": host, **({"origin": origin} if origin else {})}
        self.query_params = {"token": token} if token else {}
        self.cookies = {}
        # comme starlette : l'URL d'un WebSocket porte l'hôte, le port et le schéma de l'en-tête Host
        name, _, port = host.partition(":")
        self.url = type("U", (), {"hostname": name, "port": int(port) if port else None, "scheme": "ws"})()
        self.client = type("C", (), {"host": client})()


def test_ws_une_page_etrangere_ne_lit_pas_letat_meme_en_local():
    assert auth.allowed_ws(WS(origin="http://evil.example")) is False
    assert auth.allowed_ws(WS(origin="https://evil.example:8770")) is False


def test_ws_lapp_servie_par_le_bridge_passe(monkeypatch):
    assert auth.allowed_ws(WS()) is True                                               # pas d'Origin (outil)
    assert auth.allowed_ws(WS(origin="http://localhost:8770")) is True                 # la fenêtre du rack
    assert auth.allowed_ws(WS(host="127.0.0.1:8770", origin="http://127.0.0.1:8770")) is True
    monkeypatch.setattr(auth, "_valid", lambda t: t == "tok")
    lan = dict(client="192.168.0.25", host="192.168.0.22:8770", origin="http://192.168.0.22:8770")
    assert auth.allowed_ws(WS(token="tok", **lan)) is True                            # le Companion, appairé
    assert auth.allowed_ws(WS(**lan)) is False                                         # sans jeton
    assert auth.allowed_ws(WS(token="tok", client="192.168.0.25", host="192.168.0.22:8770",
                              origin="http://evil.example")) is False                 # jeton rejoué par un tiers
    assert auth.allowed_ws(WS(host="evil.example:8770", origin="http://evil.example:8770")) is False


# ── (b) un seul lecteur des corps d'erreur, toutes les formes de golem.fm ─────────────────────────
def test_error_text_lit_les_quatre_formes():
    assert golemfm.error_text({"detail": "song not found"}) == "song not found"
    assert golemfm.error_text({"detail": {"error": "not_ready"}}) == "not_ready"
    t = golemfm.error_text({"detail": {"error": "no_bar_map", "message": "No bar map yet"}})
    assert t == "No bar map yet (no_bar_map)"                       # la phrase, et le code gardé
    t = golemfm.error_text({"detail": {"code": "bad_recipe", "errors": ["missing gain", {"msg": "bad type"}]}})
    assert "missing gain" in t and "bad type" in t and "bad_recipe" in t
    t = golemfm.error_text({"detail": [{"loc": ["body", "name"], "msg": "field required", "type": "missing"},
                                       {"loc": ["query", "n"], "msg": "not an int", "type": "int"}]})
    assert t == "name: field required; query.n: not an int"
    assert golemfm.error_text({"error": "not_ready"}) == "not_ready"                     # racine (hors FastAPI)
    assert golemfm.error_text({"message": "quota"}) == "quota"
    assert golemfm.error_text({}, "HTTP Error 500") == "HTTP Error 500"
    assert golemfm.error_text(b"<html>oops</html>", "HTTP Error 502") == "HTTP Error 502"


def _http_error(code, body):
    return urllib.error.HTTPError("https://golem.fm/x", code, "err", {}, io.BytesIO(json.dumps(body).encode()))


@pytest.fixture
def paired(real_cfg, monkeypatch):
    monkeypatch.setattr(RC, "_load_integrations", lambda: {"golemfm": {"base_url": "https://golem.fm", "token": "gmt_x"}})


@pytest.mark.parametrize("body,want", [
    ({"detail": {"error": "not_ready"}}, "not_ready"),
    ({"detail": {"error": "x", "message": "Stems are separating"}}, "Stems are separating (x)"),
    ({"detail": [{"loc": ["body", "id"], "msg": "field required"}]}, "id: field required"),
    ({"error": "not_ready"}, "not_ready"),
])
def test_tous_les_clients_http_lisent_le_meme_message(paired, monkeypatch, body, want):
    def boom(*a, **k):
        raise _http_error(404, body)
    monkeypatch.setattr(golemfm.urllib.request, "urlopen", boom)
    assert golemfm._req("/api/ext/karaoke/1", token="gmt_x") == (404, want)
    assert tones_sync._req("POST", "/api/ext/tones/jobs/1/ack", body={}) == (404, want)    # ack / progress
    assert golemfm.put_bytes("/api/ext/x", b"1") == (404, want)


def test_karaoke_reconnait_toujours_not_ready(paired, monkeypatch):
    """karaoke.fetch cherche « not_ready » dans le texte : le code reste dedans même à côté d'une phrase."""
    def boom(*a, **k):
        raise _http_error(404, {"detail": {"error": "not_ready", "message": "Still separating"}})
    monkeypatch.setattr(golemfm.urllib.request, "urlopen", boom)
    st, info = golemfm._req("/api/ext/karaoke/1", token="gmt_x")
    assert st == 404 and "not_ready" in str(info)


# ── (c) la règle https tient là où l'adresse est LUE ──────────────────────────────────────────────
@pytest.mark.parametrize("url,ok", [
    ("https://golem.fm", True), ("http://localhost:5173", True), ("http://192.168.1.10:8000", True),
    ("http://studiopc.local:8000", True), ("http://golem.fm", False), ("http://8.8.8.8", False),
])
def test_cfg_refuse_un_serveur_en_clair_hors_du_reseau_local(real_cfg, monkeypatch, url, ok):
    monkeypatch.setattr(RC, "_load_integrations", lambda: {"golemfm": {"base_url": url, "token": "gmt_secret"}})
    base, tok = golemfm._cfg()
    if ok:
        assert (base, tok) == (url, "gmt_secret")
    else:
        assert (base, tok) == ("", "")                        # ni adresse ni jeton : rien ne part
        sent = []
        monkeypatch.setattr(golemfm.urllib.request, "urlopen", lambda *a, **k: sent.append(a))
        assert golemfm._req("/api/ext/songs", token=tok)[0] == 0 and tones_sync._req("GET", "/x")[0] == 0
        assert not sent
        st = golemfm.status()
        assert st["configured"] is False and "https" in st["error"]


def test_golemfm_url_de_lenvironnement_ne_contourne_pas_la_regle(real_cfg, monkeypatch, tmp_path):
    monkeypatch.setattr(RC, "_INTEGRATIONS_PATH", str(tmp_path / "integrations.json"))
    monkeypatch.setenv("GOLEM_SERVER_URL", "http://golem.example.com")
    monkeypatch.setenv("GOLEMFM_TOKEN", "gmt_secret")
    assert golemfm._cfg() == ("", "")


# ── (d) un id de JOB n'est jamais pris pour un id de mode ou de pack ──────────────────────────────
def test_mode_set_sans_mode_refuse_au_lieu_de_viser_lid_du_job():
    with pytest.raises(RuntimeError, match="missing id"):
        tones_jobs._mode_set({"id": 87, "_job": 87, "device": "golem-df", "action": "mode-set", "name": "x"})


def test_anim_pack_sans_pack_id_refuse(monkeypatch):
    from bridge import anim_packs
    removed = []
    monkeypatch.setattr(anim_packs, "remove", lambda pid: removed.append(pid) or {"ok": True})
    for fn in (tones_jobs._anim_pack_install, tones_jobs._anim_pack_remove):
        with pytest.raises(RuntimeError, match="missing id"):
            fn({"id": 412, "_job": 412, "action": "anim-pack-x"})
    assert removed == []
    assert tones_jobs._anim_pack_remove({"id": 412, "pack_id": "neon"}) == {"pack": {"id": "neon"}}


# ── (e) la marque ─────────────────────────────────────────────────────────────────────────────────
def test_la_presence_dit_golem():
    assert connect.presence_payload()["name"] == "golem"


def test_le_ssid_par_defaut_est_golem():
    import os
    src = open(os.path.join(os.path.dirname(__file__), "..", "provision", "setup-net-sudo.sh")).read()
    assert '"ssid": "golem"' in src and '"ssid": "GoleM"' not in src


def test_ws_une_autre_appli_de_la_machine_ne_lit_pas_letat():
    """Revue 2026-10-25 : le port de l'Origin doit être celui du bridge (un serveur de dev sur localhost:5173…)."""
    assert auth.allowed_ws(WS(origin="http://localhost:5173")) is False
