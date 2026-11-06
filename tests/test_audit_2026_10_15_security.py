# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit du 2026-10-15 (docs/audit-2026-10-15.md §1) : les quatre P0 et les paliers."""
import os
import pytest
from bridge import auth, kit_import, anim_packs
from bridge import config as C
from bridge.routes_content import server_url_ok, _within


class Req:
    def __init__(self, method, path, tok="", client="192.168.0.25", host="192.168.0.22:8770", origin=None):
        self.method = method
        self.headers = {"host": host, **({"x-golem-token": tok} if tok else {}), **({"origin": origin} if origin else {})}
        self.cookies, self.query_params = {}, {}
        self.url = type("U", (), {"path": path, "hostname": host.split(":")[0]})()
        self.client = type("C", (), {"host": client})()


DEVS = {"musician": {"id": "m"}, "guest": {"id": "g", "expires": 9e12, "person": "guest:bob"}, "admin": {"id": "a", "admin": True}}


@pytest.fixture
def devs(monkeypatch):
    monkeypatch.setattr(auth, "_device_by_token", lambda t: DEVS.get(t))


def test_s1_s2_integrations_et_relance_exigent_ladmin(devs):
    for path in ("/api/integrations", "/api/system/bridge-restart"):
        assert auth.allowed_http(Req("POST", path, "musician")) is False
        assert auth.allowed_http(Req("POST", path, "admin")) is True


def test_s1_une_valeur_de_env_ne_porte_ni_saut_de_ligne_ni_shell(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location("t3k", os.path.join(C.ROOT, "tools", "t3k.py"))
    t3k = importlib.util.module_from_spec(spec); spec.loader.exec_module(t3k)
    monkeypatch.setattr(t3k, "ENV", str(tmp_path / ".env"))
    for bad in ("x\nLD_PRELOAD=/tmp/a.so", "$(id)", "a b", "`id`"):
        with pytest.raises(ValueError):
            t3k.env_set({"T3K_PUBLISHABLE_KEY": bad})
    t3k.env_set({"T3K_PUBLISHABLE_KEY": "t3k_pub_AbC-123"})
    assert "T3K_PUBLISHABLE_KEY=t3k_pub_AbC-123" in (tmp_path / ".env").read_text()


def test_s1_le_dotenv_ne_charge_que_nos_cles(tmp_path, monkeypatch):
    p = tmp_path / ".env"
    p.write_text("LD_PRELOAD=/tmp/x.so\nPATH=/evil\nGOLEM_TEST_AUDIT=1\n")
    monkeypatch.delenv("GOLEM_TEST_AUDIT", raising=False)
    before = os.environ.get("LD_PRELOAD")
    C._load_dotenv(str(p))
    assert os.environ.get("LD_PRELOAD") == before and os.environ["PATH"] != "/evil"
    assert os.environ.get("GOLEM_TEST_AUDIT") == "1"
    monkeypatch.delenv("GOLEM_TEST_AUDIT")


def test_s2_golem_fm_en_https_hors_du_reseau_local():
    assert server_url_ok("https://golem.fm")
    assert server_url_ok("http://localhost:5173") and server_url_ok("http://192.168.1.10:8000")
    assert server_url_ok("http://studiopc.local:8000")
    assert not server_url_ok("http://golem.fm") and not server_url_ok("http://8.8.8.8")
    assert not server_url_ok("ftp://x") and not server_url_ok("javascript:alert(1)")


def test_s3_import_dun_kit_refuse_les_adresses_internes():
    for host in ("127.0.0.1", "localhost", "10.0.0.2", "192.168.1.1", "169.254.169.254", "::1"):
        with pytest.raises(ValueError):
            kit_import._public_host(host)
    with pytest.raises(ValueError):
        kit_import.fetch_url("http://127.0.0.1:8770/api/network/qr")


def test_s4_dns_rebinding_un_nom_etranger_est_refuse(devs):
    assert auth.allowed_http(Req("GET", "/api/network/qr", client="127.0.0.1", host="evil.example:8770",
                                 origin="http://evil.example:8770")) is False
    assert auth.allowed_http(Req("GET", "/api/network/qr", client="127.0.0.1", host="localhost:8770")) is True
    for ok in ("127.0.0.1:8770", "[::1]:8770", "golem.local", "10.42.0.1", "localhost"):
        assert auth.host_ok(ok), ok
    for bad in ("evil.example", "a.b.c:8770", "golem.local.evil.com"):
        assert not auth.host_ok(bad), bad


def test_paliers_invite_et_config(devs):
    assert auth.allowed_http(Req("DELETE", "/api/take/2026-10-15", "guest")) is False
    assert auth.allowed_http(Req("DELETE", "/api/take/2026-10-15", "musician")) is True
    assert auth.allowed_http(Req("POST", "/api/mode/update", "musician")) is False
    assert auth.allowed_http(Req("POST", "/api/devices/usb1", "musician")) is False
    assert auth.allowed_http(Req("GET", "/api/inputmap", "musician")) is True
    assert auth.allowed_http(Req("POST", "/api/recall", "guest")) is True        # jouer reste permis
    for path in ("/api/peaks", "/api/sample", "/api/kits/import/job/abc"):
        assert auth.allowed_http(Req("GET", path)) is False


def test_chemins_confines(tmp_path):
    (tmp_path / "samples").mkdir(); (tmp_path / "samplesX").mkdir()
    (tmp_path / "samplesX" / "a.wav").write_text("x")
    base = str(tmp_path / "samples")
    assert _within(base, "../samplesX/a.wav") is None
    assert _within(base, "/etc/passwd") is None
    assert _within(base, "kick.wav") == os.path.join(os.path.realpath(base), "kick.wav")


def test_anim_packs_ne_chargent_rien_par_un_detour():
    bad = (".anim-x-a{background:\\75rl(http://e.com/a)}", '.anim-x-a{background:image-set("https://e" 1x)}',
           ".anim-x-a ~ *{color:red}", ".anim-x-a + div{color:red}")
    for css in bad:
        assert anim_packs._check_css(css, "x")[0] is False, css
    assert anim_packs._check_css(".anim-x-a:nth-child(2n+1)>i{opacity:.5}", "x")[0] is True


def test_les_sondes_de_developpement_exigent_l_admin(devs):
    for path in ("/api/projreload", "/api/loadtest", "/api/fxprobe", "/api/rig_recall"):
        assert auth.allowed_http(Req("POST", path, "musician")) is False, path
        assert auth.allowed_http(Req("POST", path, client="127.0.0.1", host="localhost:8770")) is True, path
    assert auth.allowed_http(Req("POST", "/api/meters", "musician")) is True          # l'app s'en sert
