# SPDX-License-Identifier: GPL-3.0-or-later
"""L'analyse d'une mesure de module (bridge/drumlearn.py, docs/calibration.md addendum 2026-09-23).

Le décor est la VRAIE mesure de l'Alesis Nitro du 2026-09-23 (séquences horodatées de check-drums.py),
avec ses pièges tels qu'ils sont arrivés : le chick avant la frappe, la rafale d'aftertouch de la
pédale, les cercles de tom qui rendent la peau à vélocité 13, le geste « pédale seule » qui a rendu la
note de l'ouverte. Un test qui tient sur cette mesure tient sur ce module.
"""
import json

import pytest

from bridge import drumlearn as D
from bridge import drumkits


def ev(k, n, v, t=0.0, c=9):
    return {"k": k, "n": n, "v": v, "c": c, "t": t}


N, CCE, AT = D.NOTE, D.CC, D.POLY
BURST = lambda t: [ev(AT, 46, 127, t), ev(AT, 23, 127, t + .001), ev(AT, 42, 127, t + .002), ev(AT, 21, 127, t + .003)]


def nitro_measure(pedal_ok=False):
    """Ce que la Nitro a envoyé, étape par étape. `pedal_ok` = l'étape « pédale seule » refaite proprement."""
    steps = {
        "kick": [ev(N, 36, 94)], "snare": [ev(N, 38, 92)], "snare-rim": [ev(N, 40, 114)],
        # les cercles : la peau à 10-14, plus une diaphonie sur le pad voisin (49/51) dont la vélocité n'a
        # pas été gardée par la première capture — posée faible ici, comme l'est un coup transmis par le rack
        "tom1": [ev(N, 48, 74)], "tom1-rim": [ev(N, 48, 13), ev(N, 49, 6, .01)],
        "tom2": [ev(N, 45, 77)], "tom2-rim": [ev(N, 45, 14), ev(N, 49, 5, .01)],
        "tom3": [ev(N, 43, 86)], "tom3-rim": [ev(N, 43, 10), ev(N, 51, 4, .01)],
        "tom4": [], "tom4-rim": [],
        "hh-closed": BURST(6.679) + [ev(N, 44, 94, 6.683), ev(N, 42, 102, 8.557)],
        "hh-open": [ev(N, 46, 91)],
        "hh-half": BURST(4.372) + [ev(N, 46, 67, 6.369)],
        "hh-pedal": [ev(N, 44, 94, 1.0)] if pedal_ok else [ev(N, 46, 31, 4.637), ev(N, 46, 84, 7.381)],
        "hh-splash": [ev(N, 46, 101, 6.568)] + BURST(6.705) + [ev(N, 44, 104, 6.709)],
        "crash1": [ev(N, 49, 100)], "crash1-choke": [ev(N, 49, 103, 8.458), ev(N, 49, 35, 8.754)],
        "crash2": [], "ride": [ev(N, 51, 94)], "ride-bell": [ev(N, 51, 47), ev(N, 51, 50, .3)],
    }
    return {"port": "Alesis Nitro", "kit": "alesis-nitro", "measured_at": "2026-09-23", "clock": True,
            "steps": {k: {"events": v} for k, v in steps.items()}}


def test_la_frappe_est_la_plus_forte_sauf_le_splash_ou_c_est_la_premiere():
    assert D.strike([ev(N, 44, 94), ev(N, 42, 102, 2.0)]) == ((42, 102), [(44, 94)])       # chick puis frappe
    assert D.strike([ev(N, 46, 101), ev(N, 44, 104, .1)], pick="first") == ((46, 101), [(44, 104)])
    assert D.strike([ev(AT, 46, 127)]) == (None, [])


def test_la_mesure_nitro_lue_comme_elle_est():
    r = D.analyse(nitro_measure())
    e = r["elements"]
    assert e["hh-closed"]["note"] == 42 and [44, 94] in e["hh-closed"]["also"] and "twins" in e["hh-closed"]["flags"]
    assert e["tom1-rim"]["note"] == 48 and "weak" in e["tom1-rim"]["flags"]
    assert r["twins"]["tom1-rim"] == "tom1" and r["twins"]["ride-bell"] == "ride" and r["twins"]["hh-half"] == "hh-open"
    assert r["hihat"] == {"cc": None, "positions": 2, "notes": {"hh-closed": 42, "hh-open": 46, "hh-half": 46,
                                                                 "hh-pedal": 46, "hh-splash": 46}}
    assert r["choke"] == "none"                                   # attraper le crash n'a rien envoyé
    assert set(r["aftertouch_elsewhere"]) == {"hh-closed", "hh-half", "hh-splash"}   # la pédale, pas un choke
    assert r["channel"] == [10] and r["clock"] is True and set(r["skipped"]) == {"tom4", "tom4-rim", "crash2"}
    # le geste « pédale seule » a rendu 46 = la note de l'ouverte : deux éléments de BASE sur une note
    assert r["clash"] == {46: ["hh-open", "hh-pedal"]}


def test_une_mesure_qui_se_contredit_ne_donne_pas_de_descripteur(tmp_path, monkeypatch):
    r = D.analyse(nitro_measure())
    with pytest.raises(ValueError, match="hh-open"):
        D.descriptor(r, nitro_measure(), drumkits.get("alesis-nitro"))


def test_la_mesure_propre_donne_le_descripteur_verified_de_la_nitro():
    m = nitro_measure(pedal_ok=True)
    r = D.analyse(m)
    assert r["clash"] == {}
    base = json.load(open("config/drumkits/alesis-nitro.json", encoding="utf8"))
    base["hihat"] = {"cc": 4, "open_value": 0, "closed_value": 127, "positions": 3, "bands": [33, 66], "notes": "distinct"}
    base["choke"] = "poly-aftertouch"                              # ce que le manuel/forums disaient
    base["map"] = {**base["map"], "23": "hh-half", "21": "hh-splash", "50": "tom1-rim", "57": "crash2"}
    base["provenance"] = {"source": "manual", "confidence": "reported", "note": "manuel v1.2", "url": "http://x"}
    cmp_ = D.compare(r, base)
    st = {row["el"]: row["status"] for row in cmp_["rows"]}
    assert st["kick"] == "ok" and st["tom1-rim"] == "twin" and st["hh-half"] == "twin"
    assert not cmp_["verdict"]["hihat_cc"]["ok"] and not cmp_["verdict"]["choke"]["ok"] and cmp_["verdict"]["channel"]["ok"]
    assert {g["el"] for g in cmp_["ghosts"]} == {"crash2"}          # 23/21/50 sont pris par des jumeaux, dits ailleurs
    d = D.descriptor(r, m, base)
    assert d["map"] == {"36": "kick", "38": "snare", "40": "snare-rim", "42": "hh-closed", "43": "tom3", "44": "hh-pedal",
                        "45": "tom2", "46": "hh-open", "48": "tom1", "49": "crash1", "51": "ride"}
    assert d["hihat"] == {"cc": None, "positions": 2, "notes": "distinct"} and d["choke"] == "none" and d["channel"] == 10
    p = d["provenance"]
    assert p["source"] == "measured" and p["confidence"] == "verified" and p["measured_on"] == "Alesis Nitro"
    assert p["reported_note"] == "manuel v1.2" and p["reported_url"] == "http://x" and "note" not in p or "mesurée" in p["note"]
    assert p["reported_map"] == {"21": "hh-splash", "23": "hh-half", "50": "tom1-rim", "57": "crash2"}
    assert drumkits.validate(d, "alesis-nitro") == []


def test_un_module_inconnu_nait_de_la_mesure_et_est_valide(tmp_path, monkeypatch):
    m = nitro_measure(pedal_ok=True)
    m["port"] = "Roland TD-07"
    r = D.analyse(m)
    d = D.descriptor(r, m, None)
    assert d["id"] == "roland-td-07" and d["identity"]["usb_names"] == ["Roland TD-07"] and "audio_outs" not in d
    assert drumkits.validate(d, "roland-td-07") == []
    monkeypatch.setattr(drumkits, "DIR", str(tmp_path))
    monkeypatch.setattr(drumkits, "LOCAL_DIR", str(tmp_path))   # les mesures aussi : jamais config/ réel
    path = D.write(d)
    assert json.load(open(path, encoding="utf8"))["provenance"]["confidence"] == "verified"
    D.write(d)                                                    # une 2e écriture garde l'ancienne en .bak
    assert (tmp_path / "roland-td-07.json.bak").exists()


def test_un_cc_de_charleston_vu_pendant_les_etapes_de_charleston_est_declare():
    m = nitro_measure(pedal_ok=True)
    m["steps"]["hh-closed"]["events"] += [ev(CCE, 4, 127, 6.0)]
    m["steps"]["hh-open"]["events"] += [ev(CCE, 4, 0, .5)]
    m["steps"]["hh-half"]["events"] = [ev(CCE, 4, 60, .1), ev(N, 23, 70, .5)]     # une vraie mi-course
    r = D.analyse(m)
    assert r["hihat"]["cc"] == 4 and r["hihat"]["cc_range"] == [0, 127] and r["hihat"]["positions"] == 3
    d = D.descriptor(r, m, None)
    assert d["hihat"]["cc"] == 4 and d["hihat"]["open_value"] == 0 and d["hihat"]["closed_value"] == 127
    assert d["hihat"]["positions"] == 3 and d["hihat"]["bands"] == [33, 66] and d["map"]["23"] == "hh-half"
    assert drumkits.validate(d, d["id"]) == []


def test_le_choke_ne_se_lit_que_pendant_l_etape_d_etouffement():
    m = nitro_measure(pedal_ok=True)
    m["steps"]["crash1-choke"]["events"] += [ev(AT, 49, 127, 8.6)]
    assert D.analyse(m)["choke"] == "poly-aftertouch"
    m["steps"]["crash1-choke"]["events"] = [ev(N, 49, 100, 8.4), ev(N, 49, 0, 8.6)]
    assert D.analyse(m)["choke"] == "note-off"


def test_le_chick_se_deduit_du_geste_ferme_quand_la_pedale_seule_est_passee():
    """Stepper au vrai kit (23/09 soir) : « pédale seule » passée -> le descripteur perdait 44. Or le
    geste « fermé » contient le chick (44@94) avant la frappe (42@102) : c'est la pédale, déduite et dite."""
    m = nitro_measure(pedal_ok=True)
    m["steps"]["hh-pedal"] = {"events": []}                       # passée
    r = D.analyse(m)
    assert r["elements"]["hh-pedal"] == {"note": 44, "vel": 94, "also": [], "flags": ["inferred"], "step": "hh-closed"}
    assert "hh-pedal" not in r["skipped"] and r["clash"] == {}
    d = D.descriptor(r, m, None)
    assert d["map"]["44"] == "hh-pedal"
    # pas de déduction si la seconde note est déjà celle d'un autre élément, ou faible
    m["steps"]["hh-closed"] = {"events": [ev(N, 46, 30), ev(N, 42, 102, 2.0)]}
    assert "hh-pedal" not in D.analyse(m)["elements"]
