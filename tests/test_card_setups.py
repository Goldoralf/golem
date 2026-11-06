# SPDX-License-Identifier: GPL-3.0-or-later
"""Les configurations de carte son voyagent par golem.fm (docs/card-setups-exchange.md, 2026-10-11) — émulé sans
golem.fm : ses réponses sont fabriquées, ses appels capturés. Carte de référence : la Volt vue par Windows
(semis : IN 1 guitare, IN 2 voix) ; la sœur Linux dit l'inverse (la vraie divergence mesurée le 2026-10-10)."""
import copy
import json
import os

import pytest

from bridge import card_setups as CS, inputmap, rigstatus

VOLT = "asio:Universal Audio Volt"
SIB = {"rack": "rack-linux", "rack_name": "Rack", "os": "linux", "card": "hw:V276", "updated_at": "2026-10-04T09:12:00Z",
       "received_at": "2026-10-10T20:00:00Z", "fingerprint": "fp-linux-1", "same": False,
       "inputs": [{"slot": "IN 1", "kind": "audio", "role": "voice", "nth": 1, "name": "Voice 1", "pair": None, "person": "alex"},
                  {"slot": "IN 2", "kind": "audio", "role": "guitar", "nth": 1, "name": "Guitar 1", "pair": None, "person": "sam"}],
       "outputs": [{"slot": "OUT 1-2", "role": "monitors", "type": "wedge", "pair": "1-2", "person": None}],
       "midi_in": "fcb", "midi_out": "whammy-dt"}


@pytest.fixture
def rack(monkeypatch, tmp_path):
    """Un rack émulé : input maps dans tmp, état local dans tmp, roster {alex}, golem.fm fabriqué."""
    from bridge import cards
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path / "inputmaps"))
    os.makedirs(tmp_path / "inputmaps")
    monkeypatch.setattr(inputmap, "_card_channels", lambda device: (2, 2))
    monkeypatch.setattr(inputmap, "_card_device", lambda: VOLT)
    monkeypatch.setattr(inputmap, "_people", lambda: {"alex": "Alex"})
    monkeypatch.setattr(inputmap, "usb_ports", lambda: [])
    monkeypatch.setattr(cards, "usb_of", lambda d: "2b5a:0023" if d in (VOLT, "hw:V276") else None)
    monkeypatch.setattr(CS, "STATE_PATH", str(tmp_path / ".card-setups.json"))
    monkeypatch.setattr(CS, "_CACHE", {})
    monkeypatch.setattr("bridge.routes_inputmap._refresh", lambda reemit=False: None)
    fm = {"calls": [], "siblings": [copy.deepcopy(SIB)], "offers": [], "reply_code": 200, "down": False}

    def http(method, path, body=None, timeout=15):
        fm["calls"].append((method, path, body))
        if fm["down"]:
            return 0, {"error": "unreachable"}
        if method == "GET":
            return 200, {"usb": "2b5a:0023", "fingerprint": "fp-here", "siblings": copy.deepcopy(fm["siblings"]), "offers": copy.deepcopy(fm["offers"])}
        if path.endswith("/offers"):
            return 202, {"offer_id": "of-1", "fingerprint": "fp-sent"}
        if "/reply" in path:
            return fm["reply_code"], {}
        return 404, {"error": "?"}
    monkeypatch.setattr(CS, "_http", http)
    return fm


def _roles(dev=VOLT):
    m = inputmap.current(dev)
    return [(e["ch"], e["role"], e.get("person")) for e in m["inputs"]]


def test_le_battement_porte_l_identite_et_la_date_de_la_configuration(rack, monkeypatch):
    from bridge import modes, cards
    monkeypatch.setattr(modes, "list_modes", lambda: [])
    monkeypatch.setattr(cards, "connected", lambda: [])
    monkeypatch.setattr(cards, "present_usb_ids", lambda: set())
    monkeypatch.setattr(cards, "registry", lambda: [])
    inputmap.current(VOLT)                                               # semé, donc daté
    c = next(x for x in rigstatus.cards_doc() if x["card"] == VOLT)
    assert c["usb"] == "2b5a:0023" and c["serial"] is None and c["updated_at"].endswith("Z")
    assert [(i["slot"], i["role"]) for i in c["inputs"]] == [("IN 1", "guitar"), ("IN 2", "voice")]
    assert "os" not in c and "rack" not in c and "fingerprint" not in c   # golem.fm les lit ailleurs (§10)


def test_le_statut_dit_les_soeurs_qui_different_et_la_question_de_premiere_rencontre(rack):
    inputmap.current(VOLT)                                               # première rencontre : semis + ask
    s = CS.status(VOLT)
    assert s["usb"] == "2b5a:0023" and s["reachable"] is True
    assert [x["rack"] for x in s["siblings"]] == ["rack-linux"] and s["differs"] is True and s["ask"] is True
    assert s["local"]["inputs"][0]["role"] == "guitar"
    rack["siblings"][0]["same"] = True
    CS._CACHE.clear()
    assert CS.status(VOLT)["differs"] is False                          # identiques (lu chez golem.fm) : pas de chip


def test_sans_golem_fm_rien_ne_casse_et_les_propositions_recues_restent_visibles(rack):
    rack["down"] = True
    s = CS.status(VOLT)
    assert s["reachable"] is False and s["siblings"] == [] and s["differs"] is False and s["ask"] is False
    CS.on_job({"offer_id": "of-9", "from_rack": "rack-linux", "from_name": "Rack", "usb": "2b5a:0023", "setup": SIB})
    assert [o["offer_id"] for o in CS.status(VOLT)["offers"]] == ["of-9"]


def test_appliquer_la_configuration_de_la_soeur_par_les_setters(rack):
    assert _roles() == [("1", "guitar", None), ("2", "voice", None)]  # le semis Volt
    r = CS.use_sibling(VOLT, "rack-linux")
    assert _roles() == [("1", "voice", "alex"), ("2", "guitar", None)]  # inversé, alex gardé, sam (inconnu) vidé
    assert any("sam" in x for x in r["skipped"]) and r["applied"] >= 3
    m = inputmap.current(VOLT)
    assert m["outputs"][0]["ch"] == "1-2" and m["outputs"][0]["role"] == "monitors" and m["outputs"][0].get("type") == "wedge"
    assert (m.get("midi_in") or {}).get("role") == "fcb" and (m.get("midi_out") or {}).get("role") == "whammy-dt"
    assert CS.status(VOLT)["ask"] is False                               # la question ne se repose pas


def test_garder_separees_memorise_le_fingerprint_de_golem_fm(rack):
    inputmap.current(VOLT)
    assert CS.separate(VOLT, "rack-linux") is True
    assert json.load(open(CS.STATE_PATH))["2b5a:0023"]["separate"] == {"rack-linux": "fp-linux-1"}
    CS._CACHE.clear()
    s = CS.status(VOLT)
    assert s["differs"] is False and s["siblings"][0]["separate"] is True and s["ask"] is False
    rack["siblings"][0]["fingerprint"] = "fp-linux-2"                    # la sœur a changé : le chip revient
    CS._CACHE.clear()
    assert CS.status(VOLT)["differs"] is True


def test_proposer_sa_configuration_au_rack(rack):
    inputmap.current(VOLT)
    st, res = CS.offer(VOLT, "rack-linux")
    assert st == 202 and res["offer_id"] == "of-1"
    m, path, body = rack["calls"][-1]
    assert (m, path) == ("POST", CS.EXT + "/offers") and body["to_rack"] == "rack-linux" and body["usb"] == "2b5a:0023"
    assert [(i["slot"], i["role"]) for i in body["setup"]["inputs"]] == [("IN 1", "guitar"), ("IN 2", "voice")]
    assert "fingerprint" not in body and "os" not in body               # golem.fm les calcule / les lit lui-même


def test_une_proposition_recue_est_montree_puis_appliquee_ou_declinee(rack):
    inputmap.current(VOLT)
    job = {"id": 7, "offer_id": "of-3", "from_rack": "rack-linux", "from_name": "Rack", "offered_at": "x",
           "usb": "2b5a:0023", "serial": None, "card": "hw:V276", "os": "linux", "fingerprint": "fp-linux-1", "setup": SIB}
    assert CS.on_job(job) == {"status": "shown"}
    assert _roles()[0][1] == "guitar"                                    # rien n'est appliqué à la réception
    assert CS.on_job(dict(job, offer_id="of-4"))["status"] == "shown"
    assert [o["offer_id"] for o in CS._state()["2b5a:0023"]["offers"]] == ["of-4"]   # une seule par rack d'origine
    r = CS.reply(VOLT, "of-4", "declined")
    assert r["status"] == "declined" and _roles()[0][1] == "guitar" and CS._state()["2b5a:0023"]["offers"] == []
    assert rack["calls"][-1][1].endswith("/offers/of-4/reply") and rack["calls"][-1][2] == {"status": "declined"}
    CS.on_job(dict(job, offer_id="of-5"))
    rack["reply_code"] = 410                                             # effacée chez golem.fm entre-temps : pas d'erreur
    r = CS.reply(VOLT, "of-5", "applied")
    assert r["golem_fm"] == 410 and _roles()[0] == ("1", "voice", "alex") and CS._state()["2b5a:0023"]["offers"] == []
    with pytest.raises(ValueError):
        CS.reply(VOLT, "of-5", "applied")                                # plus connue nulle part : rien à appliquer


def test_la_premiere_rencontre_ne_concerne_que_les_cartes_identifiees(rack):
    inputmap.current("asio:ASIO4ALL v2")                                 # pas de clé USB : pas de question
    assert "ask" not in json.dumps(CS._state())
    inputmap.current(VOLT)
    assert CS._state()["2b5a:0023"]["ask"] is True
    CS.ask_later(VOLT)
    assert CS.status(VOLT)["ask"] is False and CS.status(VOLT)["differs"] is True   # « Later » : le chip reste


def test_une_identite_une_configuration_par_rack_dans_le_battement(rack, monkeypatch):
    """La même Volt sous deux noms (active `asio:…`, déclarée par un mode `hw:V276`) : seule l'active porte la clé USB —
    sinon golem.fm rangeait la dernière reçue, celle du mode (guitare IN 1), à la place de celle qui joue."""
    from bridge import modes, cards
    monkeypatch.setattr(modes, "list_modes", lambda: [{"id": "studio", "card": "hw:V276"}])
    monkeypatch.setattr(modes, "card_of", lambda m: m.get("card"))
    monkeypatch.setattr(cards, "connected", lambda: [])
    monkeypatch.setattr(cards, "present_usb_ids", lambda: set())
    monkeypatch.setattr(cards, "registry", lambda: [])
    doc = {c["card"]: c for c in rigstatus.cards_doc()}
    assert doc[VOLT]["usb"] == "2b5a:0023" and doc[VOLT]["active"] is True
    assert "hw:V276" in doc and doc["hw:V276"]["usb"] is None
