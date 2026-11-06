# SPDX-License-Identifier: GPL-3.0-or-later
"""Appareils et personnes (docs/devices-people.md, lots A, B, C) : une invitation porte une personne du
groupe ou un invité, expire en 15 min ; l'appareil d'un invité expire en 24 h ; un jeton inconnu se dit ;
le code d'appairage du premier écran donne un appareil admin, une fois, et meurt après 10 essais ratés.
`.venv/bin/python -m pytest tests/test_devices_people.py -q`"""
import json

import pytest

from bridge import auth, config as C


@pytest.fixture
def db(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setattr(auth, "DEVICES_PATH", str(tmp_path / "config" / "auth-devices.json"))
    monkeypatch.setattr(auth, "TOKEN_PATH", str(tmp_path / "config" / "auth.token"))
    monkeypatch.setattr(auth, "_db", None)
    monkeypatch.setattr(auth, "_mac_of", lambda ip: "")
    json.dump({"band": {"id": "b1"}, "people": [{"id": "alex", "name": "Alex"}, {"id": "ju", "name": "Ju"}]},
              open(tmp_path / "config" / ".band.json", "w"))
    clock = {"t": 1_000_000}
    monkeypatch.setattr(auth, "_now", lambda: clock["t"])
    return clock


class Req:
    def __init__(self, tok=""):
        self.headers = {"x-golem-token": tok} if tok else {}
        self.cookies, self.query_params = {}, {}


def test_une_invitation_porte_une_personne_du_groupe_ou_un_invite(db):
    inv = auth.create_invite(None, "Phone", person="alex")
    assert inv["name"] == "Alex" and inv["role"] is None          # le type d'appareil se lit au scan
    assert auth.create_invite(None, "Phone", person="zoe") == {"error": "this person is not in the band"}
    got = auth.claim(auth.invite_token(inv["id"]),
                     ua="Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/129.0 Mobile Safari/537.36")
    dev = auth.device_of(Req(got["token"]))
    assert (dev["person"], dev["person_name"], dev["kind"], dev["name"]) == ("alex", "Alex", "Phone", "Alex · Phone")
    g = auth.create_invite("Drums", "Phone", guest="Max")
    gt = auth.claim(auth.invite_token(g["id"]))["token"]
    gd = auth.device_of(Req(gt))
    assert gd["person"] == "guest:max" and gd["person_name"] == "Max" and gd["role"] == "Drums"
    db["t"] += 24 * 3600 + 1
    assert auth.device_of(Req(gt)) is None and auth.token_state(Req(gt)) == "unknown"   # l'invité d'hier soir
    assert auth.device_of(Req(got["token"]))["person"] == "alex"                          # le musicien du groupe, lui, reste
    row = next(d for d in auth.list_devices()["devices"] if d["person"] == "guest:max")
    assert row["expired"] is True
    auth.extend(row["id"])
    assert auth.device_of(Req(gt))["person_name"] == "Max"


def test_le_type_d_appareil_se_lit_au_scan():
    """Plus de choix « Phone / Tablet / Computer » à l'ajout (2026-10-03) : le User-Agent le dit."""
    k = auth.kind_from_ua
    assert k("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) Mobile/15E148 Safari/604.1") == "Phone"
    assert k("Mozilla/5.0 (Linux; Android 14; SM-S918B) Chrome/129.0 Mobile Safari/537.36") == "Phone"
    assert k("Mozilla/5.0 (Linux; Android 13; SM-X710) Chrome/129.0 Safari/537.36") == "Tablet"   # pas « Mobile »
    assert k("Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) Safari/604.1") == "Tablet"
    assert k("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/129.0 Safari/537.36") == "Computer"
    assert k("") is None


def test_une_invitation_non_scannee_expire(db):
    inv = auth.create_invite("Guitar", "Phone")
    tok = auth.invite_token(inv["id"])
    db["t"] += auth.INVITE_TTL + 1
    assert auth.claim(tok) is None and auth.list_devices()["invites"] == []


def test_l_etat_du_jeton_distingue_absent_et_inconnu(db):
    assert auth.token_state(Req()) == "none"
    assert auth.token_state(Req("not-a-token")) == "unknown"


def test_un_musicien_parti_du_groupe_est_signale_jamais_revoque_en_silence(db, tmp_path):
    inv = auth.create_invite(None, "Phone", person="ju")
    auth.claim(auth.invite_token(inv["id"]))
    json.dump({"people": [{"id": "alex", "name": "Alex"}]}, open(tmp_path / "config" / ".band.json", "w"))
    row = auth.list_devices()["devices"][0]
    assert row["left_band"] is True and row["person"] == "ju"


def test_le_code_d_appairage_donne_un_ecran_admin_une_fois(db):
    assert not auth.admin_exists()
    pc = auth.create_pair_code()
    assert len(pc["code"]) == 6 and auth.pair_code_pending()
    assert auth.claim_pair("000000" if pc["code"] != "000000" else "111111") is None
    got = auth.claim_pair(pc["code"], ua="Mozilla/5.0 (iPad; CPU OS 17_0)")
    dev = auth.device_of(Req(got["token"]))
    assert dev["name"] == "Rack screen" and dev["kind"] == "Tablet" and dev["admin"] is True and dev["screen"] is True
    assert auth.admin_exists() and auth.claim_pair(pc["code"]) is None      # usage unique


def test_le_code_meurt_apres_dix_essais_rates_ou_dix_minutes(db):
    pc = auth.create_pair_code()
    wrong = "123456" if pc["code"] != "123456" else "654321"
    for _ in range(auth.PAIR_TRIES):
        assert auth.claim_pair(wrong) is None
    assert auth.claim_pair(pc["code"]) is None
    pc2 = auth.create_pair_code()
    db["t"] += auth.PAIR_TTL + 1
    assert auth.claim_pair(pc2["code"]) is None


def test_dire_qui_utilise_un_appareil_deja_appaire(db):
    inv = auth.create_invite("Guitar", "Phone")
    tok = auth.claim(auth.invite_token(inv["id"]))["token"]
    did = auth.device_of(Req(tok))["id"]
    assert auth.set_person(did, person="alex") == {"ok": True}
    d = auth.device_of(Req(tok))
    assert (d["person"], d["name"], d["role"]) == ("alex", "Alex · Phone", "Guitar")
    assert auth.set_person(did, person="zoe") == {"error": "this person is not in the band"}
    assert auth.set_person("nope", person="alex") == {"error": "unknown device"}


class HttpReq:
    def __init__(self, method, path, tok="", host="192.168.0.25"):
        self.method = method
        self.headers = {"x-golem-token": tok} if tok else {}
        self.cookies, self.query_params = {}, {}
        self.url = type("U", (), {"path": path, "hostname": "192.168.0.22"})()
        self.client = type("C", (), {"host": host})()


def test_les_droits_du_groupe_donnent_le_conductor(db, tmp_path):
    """docs/devices-people.md §8 : le téléphone d'un owner ou d'un admin charge et lance d'office — c'est
    déjà lui qui décide sur golem.fm. Un member reste en lecture, et un choix fait à la main ne se réécrit pas."""
    json.dump({"band": {"id": "b1"},
               "people": [{"id": "alex", "name": "Alex", "rights": "owner"},
                          {"id": "ju", "name": "Ju", "rights": "admin"},
                          {"id": "lea", "name": "Léa", "rights": "member"}]},
              open(tmp_path / "config" / ".band.json", "w"))
    def phone(pid):
        inv = auth.create_invite(None, "Phone", person=pid)
        return auth.device_of(Req(auth.claim(auth.invite_token(inv["id"]))["token"]))
    assert phone("alex")["conductor"] is True
    assert phone("ju")["conductor"] is True
    assert phone("lea").get("conductor") in (None, False)
    # une tablette n'est pas contrainte par le conductor : on ne lui en donne pas
    inv = auth.create_invite(None, "Tablet", person="alex")
    assert auth.device_of(Req(auth.claim(auth.invite_token(inv["id"]))["token"])).get("conductor") is None
    # retiré à la main : une re-attribution de personne ne le redonne pas
    d = phone("alex")
    auth.set_conductor(d["id"], False)
    auth.set_person(d["id"], person="alex")
    assert auth.device_of(Req(next(x["token"] for x in auth._load()["devices"] if x["id"] == d["id"])))["conductor"] is False


def test_un_invite_recoit_une_duree_d_acces(db):
    """Décision 2026-09-16 : 1 jour, 1 semaine ou 1 mois — le remplaçant d'un soir et le batteur de
    tout l'automne sont deux durées du même geste. Une durée hors table retombe sur un jour."""
    inv = auth.create_invite(None, "Phone", guest="Max", days=7)
    assert inv["ttl"] == 7 * 24 * 3600
    tok = auth.claim(auth.invite_token(inv["id"]))["token"]
    row = next(d for d in auth.list_devices()["devices"] if d["person"] == "guest:max")
    assert row["guest_days"] == 7 and row["expires"] == db["t"] + 7 * 24 * 3600
    db["t"] += 6 * 24 * 3600
    assert auth.device_of(Req(tok)) is not None                      # une semaine tient la semaine
    auth.extend(row["id"], days=30)
    assert next(d for d in auth.list_devices()["devices"] if d["id"] == row["id"])["guest_days"] == 30
    assert auth.create_invite(None, "Phone", guest="Zoé", days=3)["ttl"] == auth.GUEST_TTL   # hors table
    # un invité n'est jamais conductor, quels que soient les droits lus ailleurs
    assert auth.device_of(Req(tok)).get("conductor") is None


def test_un_invite_sans_fin_reste(db):
    """Alex, 2026-11-02 : golem.fm n'ouvre pas avec la v0.6 — un membre sans compte reçoit un accès SANS FIN
    (days=0), qui dure jusqu'à ce qu'on retire l'appareil."""
    inv = auth.create_invite(None, "Phone", guest="Lou", days=0)
    tok = auth.claim(auth.invite_token(inv["id"]))["token"]
    row = next(d for d in auth.list_devices()["devices"] if d["person"] == "guest:lou")
    assert row["guest_days"] == 0 and not row.get("expires") and not row["expired"]
    db["t"] += 400 * 24 * 3600
    assert auth.device_of(Req(tok)) is not None
    g = auth.create_invite(None, "Phone", guest="Max", days=7)       # une semaine passée « sans fin »
    auth.claim(auth.invite_token(g["id"]))
    mx = next(d for d in auth.list_devices()["devices"] if d["person"] == "guest:max")
    auth.extend(mx["id"], days=0)
    mx = next(d for d in auth.list_devices()["devices"] if d["id"] == mx["id"])
    assert not mx.get("expires") and mx["guest_days"] == 0


def test_un_telephone_ne_lance_le_groupe_que_s_il_est_conductor(db):
    inv = auth.create_invite(None, "Phone", person="alex")
    tok = auth.claim(auth.invite_token(inv["id"]))["token"]
    for path in ("/api/recall", "/api/arrangement", "/api/perf/start", "/api/backing"):
        assert auth.allowed_http(HttpReq("POST", path, tok)) is False, path
    assert auth.allowed_http(HttpReq("POST", "/api/lane/stomp", tok)) is True          # ses pédales, oui
    assert auth.allowed_http(HttpReq("POST", "/api/take/flag", tok)) is True           # « Mark that », oui
    did = auth.device_of(Req(tok))["id"]
    auth.set_conductor(did, True)
    assert auth.allowed_http(HttpReq("POST", "/api/arrangement", tok)) is True
    # une tablette garde ce qu'elle avait ; le rack en local, tout
    t = auth.create_invite("Guitar", "Tablet")
    ttok = auth.claim(auth.invite_token(t["id"]))["token"]
    assert auth.allowed_http(HttpReq("POST", "/api/recall", ttok)) is True
    assert auth.allowed_http(HttpReq("POST", "/api/recall", host="127.0.0.1")) is True


def test_le_pedalier_et_le_moteur_ne_se_reecrivent_que_par_un_admin(db):
    """2026-10-03 : /api/fcb/flash était protégé, mais ce n'était plus qu'un ALIAS de /api/pedalboard/load —
    tout appareil appairé pouvait reflasher le pédalier, couper ses prises ou changer de moteur REAPER."""
    t = auth.create_invite("Guitar", "Tablet")
    tok = auth.claim(auth.invite_token(t["id"]))["token"]
    for path in ("/api/pedalboard/load", "/api/fcb/flash", "/api/pedalboard/hold", "/api/pedalboard/flashed",
                 "/api/pedalboard/select", "/api/pedalboard/learn/save",
                 "/api/system/reaper-switch", "/api/system/reaper-license"):
        assert auth.allowed_http(HttpReq("POST", path, tok)) is False, path
        assert auth.allowed_http(HttpReq("POST", path, host="127.0.0.1")) is True, path   # l'écran du rack, oui
    assert auth.allowed_http(HttpReq("POST", "/api/pedalboard/goto", tok)) is True    # changer de banque : jouer
