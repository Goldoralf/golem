# SPDX-License-Identifier: GPL-3.0-or-later
"""La carte son vue de golem.fm et les retours — lot R1 (docs/returns.md, 2026-09-26). Ce que ces tests
gardent : `cards[]` porte TOUTES les cartes qui comptent (déclarées par un mode, active, branchées) avec
leurs sorties ; une sortie porte une personne et un type ; le job `inputmap-set` passe par les setters de
l'écran, refuse tout-ou-rien (rien d'écrit), n'accepte qu'un handle du roster, et ne recâble pas la carte
active pendant une prise."""
import json
import os

import pytest

from bridge import cards, config as C, inputmap, modes, rigstatus, tones_jobs
from bridge.state import state


@pytest.fixture
def rack(tmp_path, monkeypatch):
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(inputmap, "INPUTMAPS_DIR", str(tmp_path / "maps"))
    monkeypatch.setattr(inputmap, "_card_device", lambda: "hw:V276")
    monkeypatch.setattr(inputmap, "_card_channels", lambda dev: (18, 18) if "XR18" in dev else (2, 2))
    monkeypatch.setattr(cards, "registry", lambda: [{"id": "V276", "name": "Universal Audio Volt 276"},
                                                    {"id": "XR18", "name": "Behringer X Air XR18"}])
    monkeypatch.setattr(cards, "connected", lambda: [{"index": 1, "id": "V276", "name": "Universal Audio Volt 276"}])
    monkeypatch.setattr(modes, "list_modes", lambda: [{"id": "studio", "card": "hw:V276"}, {"id": "gig", "card": "hw:XR18"},
                                                      {"id": "rehearsal", "card": "hw:XR18"}, {"id": "pedalboard"}])
    from bridge import devices
    monkeypatch.setattr(devices, "_usb_list", lambda: [])
    monkeypatch.setattr(devices, "_cards", lambda: [])
    json.dump({"people": [{"id": "alex", "name": "Alex"}, {"id": "sam", "name": "Sam"}]}, open(tmp_path / ".band.json", "w"))
    monkeypatch.setattr(rigstatus, "push_soon", lambda *a, **k: None)
    monkeypatch.setattr(rigstatus.sys, "platform", "linux")   # les clés `hw:` du test sont celles de Linux (asio: sous Windows)
    saved = (state.perf, state.backing, state.arrangement, state.mode)
    state.perf = {"recording": False}
    state.backing = {"playing": False}
    state.arrangement = {}
    state.mode = {}
    yield tmp_path
    state.perf, state.backing, state.arrangement, state.mode = saved


def test_cards_porte_toutes_les_cartes_qui_comptent_avec_leurs_sorties(rack):
    inputmap.set_person("1", "alex")                                        # la carte active (Volt)
    inputmap.set_role("output", "3-4", "iem", "hw:XR18")                  # la carte du concert, débranchée
    inputmap.set_out_person("3-4", "sam", "iem", "hw:XR18")
    docs = rigstatus.cards_doc()
    by = {c["card"]: c for c in docs}
    assert set(by) == {"hw:V276", "hw:XR18"}
    volt, xr = by["hw:V276"], by["hw:XR18"]
    assert volt["active"] and volt["connected"] and volt["modes"] == ["studio"] and volt["name"] == "Universal Audio Volt 276"
    assert volt["inputs"][0] == {"slot": "IN 1", "kind": "audio", "role": "guitar", "nth": 1, "name": "Guitar 1", "pair": None, "person": "alex"}
    assert volt["outputs"] == [{"slot": "OUT 1-2", "role": "monitors", "type": None, "pair": "1-2", "person": None}]
    assert not xr["active"] and not xr["connected"] and xr["modes"] == ["gig", "rehearsal"]
    assert len(xr["inputs"]) == 18 and len(xr["outputs"]) == 9
    assert xr["outputs"][1] == {"slot": "OUT 3-4", "role": "iem", "type": "iem", "pair": "3-4", "person": "sam"}
    v = rigstatus.patch_version(docs)
    assert len(v) == 12 and v == rigstatus.patch_version(docs)


def test_une_sortie_porte_une_personne_et_un_type_mais_pas_n_importe_lequel(rack):
    inputmap.set_out_person("1-2", "alex", "wedge")
    o = inputmap.current()["outputs"][0]
    assert o["person"] == "alex" and o["person_name"] == "Alex" and o["type"] == "wedge"
    inputmap.set_out_person("1-2", None, None)
    o = inputmap.current()["outputs"][0]
    assert "person" not in o and "type" not in o
    with pytest.raises(ValueError):
        inputmap.set_out_person("1-2", "alex", "headphones")
    with pytest.raises(ValueError):
        inputmap.set_out_person("7-8", "alex", "iem")                        # la Volt n'a pas de OUT 7-8


def test_le_job_ecrit_une_carte_non_active_et_rend_les_cartes(rack):
    r = tones_jobs._inputmap_set({"card": "XR18",
                                  "entries": [{"slot": "IN 3", "role": "voice", "nth": 1, "person": "sam"}],
                                  "outputs": [{"slot": "OUT 3-4", "role": "iem", "person": "sam", "type": "iem"}],
                                  "pairs": [{"kind": "input", "a": "5", "b": "6", "linked": True}]})
    assert r["card"] == "hw:XR18" and r["applied"] == ["IN 3", "OUT 3-4", "pair 5-6"]
    xr = next(c for c in r["cards"] if c["card"] == "hw:XR18")
    assert next(i for i in xr["inputs"] if i["slot"] == "IN 3") == {"slot": "IN 3", "kind": "audio", "role": "voice", "nth": 1, "name": "Voice 1", "pair": None, "person": "sam"}
    assert any(i["slot"] == "IN 5-6" and i["pair"] == "5-6" for i in xr["inputs"])
    assert xr["outputs"][1]["person"] == "sam" and xr["outputs"][1]["type"] == "iem"


def test_le_job_refuse_tout_ou_rien_et_ne_laisse_rien_derriere(rack):
    before = open(inputmap._path("hw:XR18")).read() if os.path.exists(inputmap._path("hw:XR18")) else None
    with pytest.raises(RuntimeError) as ex:
        tones_jobs._inputmap_set({"card": "XR18",
                                  "entries": [{"slot": "IN 3", "role": "voice"},
                                              {"slot": "IN 4", "role": "flute"},                 # instrument inconnu
                                              {"slot": "IN 5", "person": "guest:someone"}]})    # jamais un invité
    msg = str(ex.value)
    assert msg.startswith("refused, nothing written") and "IN 4: unknown instrument: flute" in msg and "IN 5:" in msg
    after = open(inputmap._path("hw:XR18")).read() if os.path.exists(inputmap._path("hw:XR18")) else None
    assert after == before                                                    # IN 3 n'a pas été écrit non plus
    with pytest.raises(RuntimeError):
        tones_jobs._inputmap_set({"card": "nope", "entries": []})              # carte inconnue du registre


def test_le_job_ne_recable_pas_la_carte_active_pendant_une_prise(rack):
    state.perf = {"recording": True}
    with pytest.raises(RuntimeError, match="a take is recording"):
        tones_jobs._inputmap_set({"card": "V276", "entries": [{"slot": "IN 1", "role": "bass"}]})
    state.perf = {"recording": False}
    state.mode = {"ui": {"locked": True}}
    with pytest.raises(RuntimeError, match="locked"):
        tones_jobs._inputmap_set({"card": "V276", "entries": [{"slot": "IN 1", "role": "bass"}]})
    state.mode = {}
    r = tones_jobs._inputmap_set({"card": "V276", "entries": [{"slot": "IN 1", "role": "bass"}]})
    assert r["applied"] == ["IN 1"] and inputmap.current()["inputs"][0]["role"] == "bass"
