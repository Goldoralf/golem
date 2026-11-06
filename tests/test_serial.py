# SPDX-License-Identifier: GPL-3.0-or-later
"""Le NUMÉRO À VIE du golem (bridge/serial.py, docs/connect.md §4.5 — contrat golem.fm du 2026-09-24).
Ce que ces tests gardent : le numéro s'écrit UNE fois et ne se réécrit jamais (un autre numéro pour la même
machine = anomalie gardée à côté, montrée, pas corrigée) ; il arrive par l'appairage OU par le battement ;
la fiche machine est une liste blanche typée ; le battement porte `rack_id` + `machine`."""
import io
import json
import os
import stat

import pytest

from bridge import config as C, connect, rigstatus, serial


@pytest.fixture
def rack(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(connect, "rack_id", lambda: "abc123")
    # ces tests-ci suivent le chemin de la PROD (le seul qui grave) ; le provisoire a les siens, en bas
    monkeypatch.setattr(serial, "is_prod", lambda base: True)
    return tmp_path


S1 = {"number": 1, "name": "golem_1", "issued_at": "2026-09-24T10:00:00Z", "machine": {"arch": "x86_64"}}


def test_le_numero_s_ecrit_une_fois_en_lecture_seule_et_ne_bouge_plus(rack):
    assert serial.record(None) == {"status": "none", "serial": None}          # pas encore attribué
    r = serial.record(S1)
    assert r["status"] == "written" and r["serial"]["name"] == "golem_1" and r["serial"]["recorded_at"]
    assert stat.S_IMODE(os.stat(rack / "serial.json").st_mode) == 0o444
    assert "machine" not in json.load(open(rack / "serial.json"))            # la fiche n'est pas le numéro
    assert serial.record(S1)["status"] == "kept"                              # idempotent (chaque battement)
    assert serial.record(None)["status"] == "none" and serial.read()["number"] == 1   # un null ne l'efface pas
    # UNE MACHINE, DEUX NUMÉROS : le premier reste, l'autre est gardé à côté et montré
    r = serial.record({"number": 7, "name": "golem_7", "issued_at": "x"})
    assert r["status"] == "conflict" and r["serial"]["name"] == "golem_1" and r["received"]["name"] == "golem_7"
    assert serial.read()["name"] == "golem_1" and serial.conflict()["received"]["number"] == 7
    assert serial.plate() == {"name": "golem_1", "number": 1, "issued_at": "2026-09-24T10:00:00Z", "conflict": "golem_7",
                              "provisional": False}


def test_un_numero_mal_forme_est_ignore(rack):
    for bad in ({"number": "1", "name": "golem_1"}, {"number": 1, "name": "rack-1"}, {"number": True, "name": "golem_1"}, "golem_1"):
        assert serial.record(bad)["status"] == "invalid", bad
    assert serial.read() is None and serial.plate()["name"] is None


def test_la_fiche_machine_est_une_liste_blanche_typee():
    m = serial.machine()
    assert set(m) == {"arch", "cpu", "cores", "ram_mb", "disk_gb", "hostname", "board"}
    assert m["cores"] is None or isinstance(m["cores"], int)
    assert m["ram_mb"] is None or isinstance(m["ram_mb"], int)
    assert m["disk_gb"] is None or isinstance(m["disk_gb"], (int, float))
    for k in ("arch", "cpu", "hostname", "board"):
        assert m[k] is None or isinstance(m[k], str)


def test_l_appairage_garde_le_numero_qui_arrive_avec_l_approbation(rack, monkeypatch):
    from bridge import golemfm as M
    monkeypatch.setattr(M, "_save_token", lambda t: None)
    M._pair.update(active=True, code="ABCD", poll_token="pt", approve_url="u", error=None)
    monkeypatch.setattr(M, "_req", lambda *a, **k: (200, {"status": "approved", "token": "gmt_x", "serial": S1}))
    assert M.pair_status() == {"active": False, "approved": True}
    assert serial.read()["name"] == "golem_1"
    # un rack approuvé SANS rack_id (ancien contrat) : `serial: null`, rien d'écrit, l'appairage passe quand même
    M._pair.update(active=True, code="ABCD", poll_token="pt", approve_url="u", error=None)
    monkeypatch.setattr(M, "_req", lambda *a, **k: (200, {"status": "approved", "token": "gmt_y", "serial": None}))
    assert M.pair_status()["approved"] is True and serial.read()["name"] == "golem_1"


def test_le_battement_porte_rack_id_et_la_fiche_et_recoit_le_numero(rack, monkeypatch):
    import urllib.request
    from bridge import golemfm as M
    monkeypatch.setattr(M, "_cfg", lambda: ("http://fm.test", "gmt_tok"))
    sent = {}

    class _Resp:
        status = 200
        def __init__(self, body): self._b = body
        def read(self): return self._b
        def __enter__(self): return self
        def __exit__(self, *a): return False

    def fake_open(req, timeout=10):
        sent["url"], sent["body"] = req.full_url, json.loads(req.data)
        sent["auth"] = req.get_header("Authorization")
        return _Resp(json.dumps({"ok": True, "serial": S1}).encode())
    monkeypatch.setattr(urllib.request, "urlopen", fake_open)
    st, err = rigstatus.push(payload={"firmware": "v2.0.0", "rack_id": connect.rack_id(), "machine": serial.machine()})
    assert (st, err) == (200, None) and sent["url"] == "http://fm.test/api/ext/rig/status" and sent["auth"] == "Bearer gmt_tok"
    assert sent["body"]["rack_id"] == "abc123" and set(sent["body"]["machine"]) >= {"arch", "cores", "hostname", "board"}
    assert serial.read()["name"] == "golem_1"                                 # reçu au premier battement
    # le payload par défaut (light) porte aussi rack_id + machine
    monkeypatch.setattr(rigstatus, "golem_version", lambda: "v2.0.0")
    monkeypatch.setattr(rigstatus, "reaper_version", lambda: "7.0")
    light = rigstatus.light()
    assert light["rack_id"] == "abc123" and isinstance(light["machine"], dict)
    # une réponse sans `serial` (ancien serveur) ne touche à rien ; une réponse vide non plus
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=10: _Resp(b""))
    assert rigstatus.push(payload={"x": 1}) == (200, None) and serial.read()["name"] == "golem_1"


def test_relire_son_numero_chez_golem_fm(rack, monkeypatch):
    from bridge import golemfm as M
    monkeypatch.setattr(M, "_cfg", lambda: ("http://fm.test", "gmt_tok"))
    calls = []
    def req(path, body=None, token=None, base=None, timeout=10, raw=False, method=None):
        calls.append((path, method, token))
        return (404, "no serial yet") if len(calls) == 1 else (200, dict(S1))
    monkeypatch.setattr(M, "_req", req)
    assert serial.fetch()["status"] == "absent"
    assert serial.fetch()["status"] == "written" and serial.read()["name"] == "golem_1"
    assert calls[0] == ("/api/ext/serial", "GET", "gmt_tok")
    monkeypatch.setattr(M, "_cfg", lambda: ("", ""))
    assert serial.fetch()["status"] == "error"


# ── SEULE LA PROD GRAVE (2026-09-29, docs/connect.md §4.5 bis) ─────────────────────────────────
@pytest.mark.parametrize("base,prod", [
    ("https://golem.fm", True), ("https://www.golem.fm/", True), ("https://private.example.net", False), ("http://golem.fm", False),
    ("http://localhost:5173", False), ("https://golem.fm.evil.test", False), ("", False), (None, False)])
def test_seule_l_origine_golem_fm_en_https_est_la_prod(base, prod):
    assert serial.is_prod(base) is prod


def test_un_numero_de_dev_est_provisoire_jamais_grave(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    r = serial.record(S1, base="http://localhost:5173")                  # la base de dev compte depuis 1, elle aussi
    assert r["status"] == "provisional" and r["serial"] is None
    assert not (tmp_path / "serial.json").exists()                          # rien de gravé
    assert serial.plate() == {"name": "golem_1", "number": 1, "issued_at": "2026-09-24T10:00:00Z",
                              "conflict": None, "provisional": True, "server": "localhost:5173"}
    # un autre numéro de dev n'est pas un « conflit » : le provisoire se réécrit
    assert serial.record({"number": 4, "name": "golem_4"}, base="http://localhost:5173")["status"] == "provisional"
    assert serial.provisional()["name"] == "golem_4" and serial.conflict() is None
    # la prod arrive : elle grave, et le provisoire s'efface
    r = serial.record({"number": 2, "name": "golem_2", "issued_at": "2026-09-29"}, base="https://golem.fm")
    assert r["status"] == "written" and serial.read()["name"] == "golem_2" and serial.read()["server"] == "golem.fm"
    assert serial.provisional() is None and serial.plate()["provisional"] is False
    # une fois gravé, un numéro de dev ne touche plus à rien — ni au fichier, ni aux conflits
    assert serial.record(S1, base="http://localhost:5173")["serial"]["name"] == "golem_2"
    assert serial.conflict() is None and serial.plate()["name"] == "golem_2"
