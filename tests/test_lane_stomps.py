# SPDX-License-Identifier: GPL-3.0-or-later
"""Ma lane, sur mon téléphone (docs/band-scenes.md, écran 5) : un appareil Bass voit et bascule les
blocs de la lane basse, jamais ceux de la guitare ; une bascule vit le temps de la scène.
`.venv/bin/python -m pytest tests/test_lane_stomps.py -q`"""
import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from test_lane_states import _v2
from bridge import lane_stomps, store


def _p():
    return store.migrate_config(json.loads(json.dumps(_v2())))


def test_un_telephone_bass_ne_voit_que_sa_lane_et_ses_pedales():
    rows = lane_stomps.mine(_p(), "B", "Bass")
    assert [r["id"] for r in rows] == ["bass-1"]
    assert [(b["id"], b["on"]) for b in rows[0]["blocks"]] == [("b-comp", True), ("b-drive", False)]   # scène B : drive coupé
    assert rows[0]["state"] == "Verse" and rows[0]["level"] == -1
    g = lane_stomps.mine(_p(), "B", "Guitar")
    assert [b["id"] for b in g[0]["blocks"]] == ["wh", "muff", "tape"]      # l'ampli et le baffle ne se basculent pas
    assert lane_stomps.mine(_p(), "B", "Drums") == []
    assert len(lane_stomps.mine(_p(), "B", None)) == 2                     # le rack en local : tout


def test_la_garde_refuse_la_lane_d_un_autre_et_le_coeur_du_son():
    p = _p()
    assert lane_stomps.check_toggle(p, "b-drive", "Bass") is None
    assert "another musician" in lane_stomps.check_toggle(p, "muff", "Bass")
    assert "not a pedal" in lane_stomps.check_toggle(p, "amp-c", "Guitar")
    assert "not in the current preset" in lane_stomps.check_toggle(p, "nope", "Guitar")
    assert lane_stomps.check_toggle(p, "muff", None) is None


def test_une_bascule_vit_le_temps_de_la_scene():
    p = _p()
    t = {"b-drive": {"on": True, "preset": "kite", "scene": "B"}}
    assert [b["on"] for b in lane_stomps.mine(p, "B", "Bass", t)[0]["blocks"]] == [True, True]
    assert lane_stomps.mine(p, "B", "Bass", t)[0]["blocks"][1]["live"] is True
    assert [b["on"] for b in lane_stomps.mine(p, "C", "Bass", t)[0]["blocks"]] == [True, True]   # C : drive écrit ON dans la scène
    assert lane_stomps.mine(p, "A", "Bass", t)[0]["blocks"][1] == {"id": "b-drive", "type": "drive", "label": None, "variant": None, "foot": None, "on": False, "live": False}


# ── docs/devices-people.md, lot A : l'appareil porte une PERSONNE, le téléphone montre ses lignes ──
IMAP = {"inputs": [{"ch": "1", "role": "guitar", "nth": 1, "person": "alex"},
                   {"ch": "2", "role": "bass", "nth": 1, "person": "jo"}],
        "usb": [{"ch": "usb1", "port": 1, "role": "keys", "bound": True, "person": "alex"}]}


def _with_keys():
    p = json.loads(json.dumps(_v2()))
    p["lanes"].append({"id": "keys-1", "role": "keys", "midi": True, "name": "Keys 1", "in_sel": "usb1",
                       "chain": {"pre": [{"id": "vit", "type": "vital"}, {"id": "k-chorus", "type": "chorus"}], "split": None, "post": []}})
    return store.migrate_config(p)


def test_alex_voit_ses_deux_lignes_guitare_et_clavier_jo_la_basse():
    p = _with_keys()
    assert [r["id"] for r in lane_stomps.mine(p, "A", None, person="alex", imap=IMAP)] == ["guitar-1", "keys-1"]
    assert [r["id"] for r in lane_stomps.mine(p, "A", "Guitar", person="jo", imap=IMAP)] == ["bass-1"]   # la personne prime sur le rôle
    rows = lane_stomps.mine(p, "A", None, person="alex", imap=IMAP)
    assert rows[1]["input"] == "USB 1" and [b["id"] for b in rows[1]["blocks"]] == ["k-chorus"]   # l'instrument ne se bascule pas
    assert lane_stomps.mine(p, "A", None, person="nobody", imap=IMAP) == []


def test_la_garde_suit_la_personne():
    p = _with_keys()
    assert lane_stomps.check_toggle(p, "k-chorus", None, person="alex", imap=IMAP) is None
    assert "another musician" in lane_stomps.check_toggle(p, "b-drive", "Bass", person="alex", imap=IMAP)
    assert lane_stomps.check_toggle(p, "b-drive", None, person="jo", imap=IMAP) is None


def test_la_personne_d_une_lane_suit_la_carte_active():
    L = {"id": "guitar-1", "role": "guitar", "in_sel": "3", "in_role": "guitar", "in_nth": 1, "midi": False}
    home = {"inputs": [{"ch": "1", "role": "guitar", "nth": 1, "person": "alex"}]}
    rehearsal = {"inputs": [{"ch": "1", "role": "voice", "nth": 1, "person": "lea"}, {"ch": "3", "role": "guitar", "nth": 1, "person": "alex"}]}
    assert lane_stomps.lane_person(L, home) == "alex" and lane_stomps.lane_person(L, rehearsal) == "alex"


def test_une_ligne_clavier_dit_le_son_de_chaque_scene():
    p = _with_keys()
    L = next(x for x in p["lanes"] if x["id"] == "keys-1")
    L["chain"]["pre"][0]["params"] = {"preset": "library/synth/vital/EP_Suitcase.vital", "zone_lo": 36, "transpose": 12}
    sc = next(s for s in p["scenes"] if s["id"] == "C")
    sc.setdefault("params", {})["vit"] = {"preset": "library/synth/vital/Warm_Pad.vital"}
    sc.setdefault("lanes", {})["keys-1"] = {**sc["lanes"].get("keys-1", {}), "mute": False}
    rows = {r["scene"]: r for r in lane_stomps.instruments_by_scene(p, L)}
    assert rows["A"]["name"] == "EP Suitcase" and rows["A"]["transpose"] == 12 and rows["A"]["instrument"] == "Vital"
    assert rows["C"]["name"] == "Warm Pad" and rows["C"]["zone_lo"] == 36
    keys = next(r for r in lane_stomps.mine(p, "A", None, person="alex", imap=IMAP) if r["id"] == "keys-1")
    assert [x["scene"] for x in keys["instruments"]] == ["A", "B", "C"]


# ── docs/drums-kit.md lot 0 : la batterie est une lane comme les autres ───────────────────────────
IMAP_DRUMS = {"inputs": [{"ch": "1", "role": "guitar", "nth": 1, "person": "alex"},
                         {"ch": "2", "role": "bass", "nth": 1, "person": "jo"},
                         {"ch": "3-4", "role": "drums", "nth": 1, "person": "sam"}],   # paire stéréo = UNE entrée
              "usb": []}


def _with_drums():
    p = json.loads(json.dumps(_v2()))
    p["lanes"].append({"id": "drums-1", "role": "drums", "in_role": "drums", "in_nth": 1, "in_sel": "3-4", "name": "Drums 1",
                       "chain": {"pre": [{"id": "d-comp", "type": "comp"}], "split": None, "post": []}})
    return store.migrate_config(p)


def test_un_appareil_drums_tient_la_lane_batterie_et_elle_est_stereo(monkeypatch):
    from bridge import inputmap
    monkeypatch.setattr(inputmap, "current", lambda *a, **k: IMAP_DRUMS)
    p = _with_drums()
    assert [r["id"] for r in lane_stomps.mine(p, "A", "Drums", imap=IMAP_DRUMS)] == ["drums-1"]     # rôle d'appareil
    assert [r["id"] for r in lane_stomps.mine(p, "A", None, person="sam", imap=IMAP_DRUMS)] == ["drums-1"]   # personne
    assert lane_stomps.check_toggle(p, "d-comp", "Drums") is None
    assert "another musician" in lane_stomps.check_toggle(p, "d-comp", "Bass")
    L = next(x for x in store.lanes_of(p) if x["id"] == "drums-1")
    assert L["stereo"] is True and L["midi"] is False and L["input"] == 3          # I_RECINPUT = 1024 + 2


def test_une_batterie_sur_un_port_usb_est_une_lane_midi():
    p = json.loads(json.dumps(_v2()))
    p["lanes"].append({"id": "drums-1", "role": "drums", "in_sel": "usb2", "name": "Drums 1",
                       "chain": {"pre": [], "split": None, "post": []}})
    L = next(x for x in store.lanes_of(store.migrate_config(p)) if x["id"] == "drums-1")
    assert L["midi"] is True and L["stereo"] is False
