# SPDX-License-Identifier: GPL-3.0-or-later
"""Se connecter sans taper d'adresse (docs/connect.md, lot R1) : les vraies adresses du rack (jamais un pont
Docker), la présence poussée à golem.fm seulement quand elle change ou au battement, le rachat d'un ticket
qui crée l'appareil de la personne — et le même téléphone qui revient retrouve SON jeton —, le transfert du
jeton vers le nom `.local`, et les portes d'auth de ces routes.
`.venv/bin/python -m pytest tests/test_connect.py -q`"""
import json

import pytest

from bridge import auth, config as C, connect


# ── les adresses ─────────────────────────────────────────────────────────────────────────────────
def _link(name, *addrs, up=True):
    return {"ifname": name, "flags": ["BROADCAST", "UP"] + (["LOWER_UP"] if up else ["NO-CARRIER"]),
            "addr_info": [dict(family=f, local=ip, scope=sc) for f, ip, sc in addrs]}


LINKS = [
    _link("lo", ("inet", "127.0.0.1", "host")),
    _link("enx0", up=False),
    _link("wlo1", ("inet", "192.168.0.22", "global"), ("inet6", "2a01:e0a:9aa:1080:7aff:f36b:7377:e0e9", "global"),
          ("inet6", "fd00::1", "global"), ("inet6", "fe80::1", "link")),
    _link("virbr0", ("inet", "192.168.122.1", "global"), up=False),
    _link("br-fd0d35102c2b", ("inet", "172.18.0.1", "global")),
    _link("docker0", ("inet", "172.17.0.1", "global")),
    _link("wlx00c0ca", ("inet", "10.42.0.1", "global")),
    _link("eno1", ("inet", "192.168.1.40", "global")),
]


def test_les_adresses_sont_celles_d_un_telephone_jamais_un_pont_virtuel():
    a = connect.addresses(LINKS, [{"prefsrc": "192.168.0.22", "dev": "wlo1"}])
    assert [x["ip"] for x in a["ipv4"]] == ["192.168.0.22", "192.168.1.40", "10.42.0.1"]   # route par défaut d'abord, AP en dernier
    assert a["primary"] == "192.168.0.22" and a["ap"] is True
    assert a["ipv6_prefixes"] == ["2a01:e0a:9aa:1080::/64"]                                 # ni ULA, ni lien-local
    # scène : pas de route par défaut, seul le point d'accès
    s = connect.addresses([_link("wlx00c0ca", ("inet", "10.42.0.1", "global"))], [])
    assert s["primary"] == "10.42.0.1" and s["ap"] is True


def test_la_presence_borne_ses_urls_et_garde_le_nom(monkeypatch):
    many = [_link(f"eth{i}", ("inet", f"192.168.{i}.2", "global")) for i in range(8)]
    monkeypatch.setattr(connect, "mdns_host", lambda: "golem-rack.local")
    monkeypatch.setattr(connect, "_wifi", lambda: {"ssid": "Studio", "ap": False, "ap_ssid": "GoleM"})
    monkeypatch.setattr(connect, "_band", lambda: "b_x")
    p = connect.presence_payload(connect.addresses(many, [{"prefsrc": "192.168.3.2"}]))
    assert len(p["urls"]) == 6 and p["urls"][0] == "http://192.168.3.2:8770" and p["urls"][-1] == "http://golem-rack.local:8770"
    assert p["rack_id"] == connect.rack_id() and len(p["rack_id"]) == 24
    mid = open("/etc/machine-id").read().strip() if __import__("os").path.exists("/etc/machine-id") else ""
    assert not mid or mid[:24] != p["rack_id"]                                              # l'id de la machine ne sort pas tel quel
    assert set(p) >= {"session", "name", "host", "port", "ipv6_prefixes", "wifi", "band", "at"}


def test_la_presence_part_au_changement_et_au_battement_seulement(monkeypatch):
    from bridge import golemfm
    sent, verdict = [], {"st": 404}
    payload = {"urls": ["http://192.168.0.22:8770"], "ipv6_prefixes": [], "wifi": {}, "band": None, "host": None}
    monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://golem.fm", "gmt_x"))
    monkeypatch.setattr(connect, "presence_enabled", lambda: True)
    monkeypatch.setattr(connect, "presence_payload", lambda addr=None: dict(payload))
    monkeypatch.setattr(connect, "push_presence", lambda p=None: sent.append(p) or verdict["st"])
    monkeypatch.setattr(connect, "_last", {"sig": None, "at": 0.0, "status": None, "warned": False})
    assert connect.tick(now=1000) == 404 and len(sent) == 1
    connect.tick(now=1030)
    assert len(sent) == 1                                                  # refusé (lot W pas livré) : pas toutes les 30 s
    verdict["st"] = 200
    payload["urls"] = ["http://192.168.1.40:8770"]
    connect.tick(now=1060)
    assert len(sent) == 2                                                  # nouvelle box : part tout de suite
    connect.tick(now=1090)
    assert len(sent) == 2                                                  # rien n'a bougé
    connect.tick(now=1060 + connect.PRESENCE_EVERY)
    assert len(sent) == 3                                                  # battement
    monkeypatch.setattr(connect, "presence_enabled", lambda: False)
    assert connect.tick(now=99999) is None and len(sent) == 3             # case décochée : rien ne part
    monkeypatch.setattr(connect, "presence_enabled", lambda: True)
    connect.tick(now=100000)
    assert len(sent) == 4                                                  # recochée : repart sans attendre le battement


# ── le rachat ────────────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def db(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(auth, "DEVICES_PATH", str(tmp_path / "config" / "auth-devices.json"))
    monkeypatch.setattr(auth, "TOKEN_PATH", str(tmp_path / "config" / "auth.token"))
    monkeypatch.setattr(auth, "_db", None)
    monkeypatch.setattr(auth, "_mac_of", lambda ip: "")
    monkeypatch.setattr(auth, "_handoffs", {})
    json.dump({"band": {"id": "b1"}, "people": [{"id": "alex", "name": "Alex"}]}, open(tmp_path / "config" / ".band.json", "w"))
    clock = {"t": 1_000_000}
    monkeypatch.setattr(auth, "_now", lambda: clock["t"])
    monkeypatch.setattr(connect, "local_url", lambda: "http://golem-rack.local:8770")
    return clock


class FakeFm:
    """golem.fm : un ticket vaut une réponse, une fois."""
    def __init__(self, monkeypatch, paired=True):
        self.tickets, self.calls = {}, []
        from bridge import golemfm, roster
        monkeypatch.setattr(golemfm, "_cfg", lambda: ("https://golem.fm", "gmt_x") if paired else ("", ""))
        monkeypatch.setattr(golemfm, "_req", self.req)
        monkeypatch.setattr(roster, "sync", lambda: self.calls.append("sync") or {"ok": True})

    def req(self, path, body=None, token=None, method=None, timeout=None, **kw):
        self.calls.append(path)
        if path != connect.REDEEM_PATH:
            return 404, "no"
        t = (body or {}).get("ticket")
        if t == "offline":
            return 0, "unreachable"
        if t not in self.tickets:
            return 410, "ticket already used"
        return 200, self.tickets.pop(t)


class Req:
    def __init__(self, tok=""):
        self.headers = {"x-golem-token": tok} if tok else {}
        self.cookies, self.query_params = {}, {}


def _ticket(fm, name, person=("alex", "Alex"), kind="Phone", client="c-phone", screen=False):
    fm.tickets[name] = {"person": None if screen else {"id": person[0], "name": person[1], "roles": ["guitar"]},
                        "band": "b1", "kind": kind, "screen": screen, "client": client}


def test_un_ticket_cree_l_appareil_de_la_personne_et_ne_sert_qu_une_fois(db, monkeypatch):
    fm = FakeFm(monkeypatch)
    _ticket(fm, "t1")
    st, got = connect.redeem("t1", ua="Mozilla/5.0 (Linux; Android 14; Pixel 8)", ip="192.168.0.30")
    assert st == 200 and got["name"] == "Alex · Phone" and got["open"] == "/app/m.html"
    assert got["local_url"] == "http://golem-rack.local:8770"
    dev = auth.device_of(Req(got["token"]))
    assert (dev["person"], dev["kind"], dev["admin"], dev["conductor"]) == ("alex", "Phone", None, None)
    assert next(d for d in auth.list_devices()["devices"])["via"] == "golem.fm"
    st, again = connect.redeem("t1")
    assert st == 410 and "expired or was already used" in again["error"]
    assert "sync" not in fm.calls                                         # le mainteneur était déjà dans le groupe


def test_le_meme_telephone_retrouve_son_jeton(db, monkeypatch):
    fm = FakeFm(monkeypatch)
    _ticket(fm, "a"); _ticket(fm, "b", kind="Phone")
    tok1 = connect.redeem("a")[1]["token"]
    tok2 = connect.redeem("b")[1]["token"]
    assert tok1 == tok2 and len(auth.list_devices()["devices"]) == 1     # le jeton sous l'IP et sous le nom restent valides
    _ticket(fm, "c", client="c-other")
    assert connect.redeem("c")[1]["token"] != tok1 and len(auth.list_devices()["devices"]) == 2


def test_une_tablette_ouvre_l_app_et_l_ecran_du_rack_est_admin_sans_personne(db, monkeypatch):
    fm = FakeFm(monkeypatch)
    _ticket(fm, "tab", kind="Tablet", client="c-tab")
    got = connect.redeem("tab")[1]
    assert got["open"] == "/app/" and got["kind"] == "Tablet"
    _ticket(fm, "scr", kind="Tablet", client="c-tab", screen=True)
    scr = connect.redeem("scr")[1]
    d = auth.device_of(Req(scr["token"]))
    assert (d["name"], d["admin"], d["screen"], d.get("person")) == ("Rack screen", True, True, None)
    _ticket(fm, "back", kind="Tablet", client="c-tab")                    # redevenue la tablette du mainteneur
    d = auth.device_of(Req(connect.redeem("back")[1]["token"]))
    assert d["person"] == "alex" and not d.get("admin") and not d.get("screen")


def test_une_personne_absente_du_cache_resynchronise_le_groupe(db, monkeypatch):
    fm = FakeFm(monkeypatch)
    _ticket(fm, "ju", person=("ju", "Ju"), client="c-ju")
    st, got = connect.redeem("ju")
    assert st == 200 and "sync" in fm.calls and got["name"] == "Ju · Phone"


def test_les_refus_se_disent(db, monkeypatch):
    fm = FakeFm(monkeypatch)
    assert connect.redeem("")[0] == 400
    assert connect.redeem("offline")[0] == 502
    fm.tickets["nobody"] = {"person": None, "kind": "Phone", "screen": False, "client": "x"}
    assert connect.redeem("nobody") == (502, {"error": "golem.fm did not say who you are."})
    FakeFm(monkeypatch, paired=False)
    st, out = connect.redeem("t")
    assert st == 409 and "not paired" in out["error"]


def test_le_transfert_pose_le_meme_jeton_une_fois_en_60_secondes(db, monkeypatch):
    fm = FakeFm(monkeypatch)
    _ticket(fm, "t")
    tok = connect.redeem("t")[1]["token"]
    did = auth.device_of(Req(tok))["id"]
    h = auth.create_handoff(did)
    got = auth.claim_handoff(h["code"])
    assert got["token"] == tok and got["open"] == "/app/m.html"
    assert auth.claim_handoff(h["code"]) is None                         # usage unique
    h2 = auth.create_handoff(did)
    db["t"] += auth.HANDOFF_TTL + 1
    assert auth.claim_handoff(h2["code"]) is None                        # trop tard
    assert auth.claim_handoff("") is None and auth.claim_handoff("nope") is None


class HttpReq:
    def __init__(self, method, path, tok="", host="192.168.0.25", origin=None):
        self.method = method
        self.headers = {"x-golem-token": tok} if tok else {}
        if origin:
            self.headers["origin"] = origin
        self.cookies, self.query_params = {}, {}
        self.url = type("U", (), {"path": path, "hostname": "192.168.0.22"})()
        self.client = type("C", (), {"host": host})()


def test_les_portes_des_routes_connect(db, monkeypatch):
    fm = FakeFm(monkeypatch)
    _ticket(fm, "t")
    tok = connect.redeem("t")[1]["token"]
    # ouvertes sans jeton, mais pas depuis une page étrangère
    for path in ("/api/auth/connect", "/api/auth/handoff/claim"):
        assert auth.allowed_http(HttpReq("POST", path)) is True, path
        assert auth.allowed_http(HttpReq("POST", path, origin="https://evil.example")) is False, path
    assert auth.allowed_http(HttpReq("POST", "/api/auth/handoff")) is False                  # il faut un appareil
    assert auth.allowed_http(HttpReq("POST", "/api/auth/handoff", tok)) is True
    assert auth.allowed_http(HttpReq("POST", "/api/connect/settings", tok)) is False         # la case : admin ou local
    assert auth.allowed_http(HttpReq("POST", "/api/connect/settings", host="127.0.0.1")) is True


def test_where_ne_montre_jamais_l_id_du_rack(monkeypatch):
    from bridge import routes_connect
    monkeypatch.setattr(connect, "where", lambda: {"rack_id": "secret", "session": "s", "urls": ["http://1.2.3.4:8770"]})
    assert routes_connect.connect_where() == {"urls": ["http://1.2.3.4:8770"]}
