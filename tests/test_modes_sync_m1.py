# SPDX-License-Identifier: GPL-3.0-or-later
"""Les modes vus et réglés depuis golem.fm — lot M1 (docs/modes.md, addendum 2026-09-26). Ce que ces tests
gardent : la feuille et le job passent par UN chemin (`modes.apply_update` / `commit`) — et « Live screen »
persiste enfin ; le job `mode-set` refuse tout-ou-rien, tient la règle d'espace, ne touche jamais au verrou ni
au kiosk, et ne recâble pas le mode actif pendant une prise ; le battement porte la feuille entière + les
vocabulaires + les configs globales ; `recorder-set` n'écrit que des clés connues, jamais pendant une prise."""
import json
import os

import pytest

from bridge import cards, config as C, modes, rigstatus, roster, store, tones_jobs
from bridge.state import state


@pytest.fixture
def rack(tmp_path, monkeypatch):
    (tmp_path / "modes").mkdir(); (tmp_path / "modes.local").mkdir()
    json.dump({"id": "rehearsal", "name": "Rehearsal", "icon": "🥁", "order": 4,
               "services": {"voice": True, "perfrec": True, "arrangement": False},
               "ui": {"pages": ["live"], "boot": "live", "locked": False}, "click_mode": "manual", "band": "b_night"},
              open(tmp_path / "modes" / "rehearsal.json", "w"))
    json.dump({"id": "gig", "name": "Gig", "icon": "🎤", "order": 5, "services": {"perfrec": True},
               "ui": {"pages": ["live"], "boot": "live", "locked": True}, "card": "hw:XR18"},
              open(tmp_path / "modes" / "gig.json", "w"))
    monkeypatch.setattr(C, "CONFIG_DIR", str(tmp_path))
    # recorder-set republie presets/.perfsrc.json — ce que golem_perfrec lit à chaque prise : sans ceci le test
    # réécrivait celui du rack en « tracks » et les prises suivantes partaient SANS DI (2026-10-29, rec 255 et 256)
    (tmp_path / "presets").mkdir()
    monkeypatch.setattr(C, "PRESETS_DIR", str(tmp_path / "presets"))
    monkeypatch.setattr(modes, "MODES_DIR", str(tmp_path / "modes"))
    monkeypatch.setattr(modes, "LOCAL_DIR", str(tmp_path / "modes.local"))
    monkeypatch.setattr(store, "RECORDER_CFG", str(tmp_path / "recorder.json"))
    monkeypatch.setattr(store, "CLICK_CFG", str(tmp_path / "click.json"))
    monkeypatch.setattr(cards, "registry", lambda: [{"id": "V276", "name": "Volt"}, {"id": "XR18", "name": "XR18"}])
    monkeypatch.setattr(roster, "read", lambda: {"bands": [{"id": "b_night", "name": "Night Shift"}, {"id": "b_earth", "name": "Earth"}]})
    monkeypatch.setattr(rigstatus, "push_soon", lambda *a, **k: None)
    saved = (state.perf, state.backing, state.arrangement, state.mode)
    state.perf = {"recording": False}; state.backing = {"playing": False}; state.arrangement = {}; state.mode = {}
    yield tmp_path
    state.perf, state.backing, state.arrangement, state.mode = saved


def _mode(mid):
    return next(m for m in modes.list_modes() if m["id"] == mid)


def test_la_feuille_et_le_job_partagent_un_chemin_et_live_screen_persiste(rack):
    m = _mode("rehearsal")
    modes.apply_update(m, {"live_view": "timeline", "click_mode": "preset", "services": {"voice": False, "bogus": True},
                           "inputs_off": ["voice#2", "nope", 3], "card": "hw:V276", "band": ""})
    saved = modes.commit(m)
    again = _mode("rehearsal")
    assert again["ui"]["live"] == "timeline" and modes.live_view(again) == "timeline"     # le bug du 26/09
    assert again["click_mode"] == "preset" and again["services"] == {"voice": False}
    assert again["inputs_off"] == ["voice#2"] and again["card"] == "hw:V276" and "band" not in again
    assert again["_modified"] and os.path.exists(rack / "modes.local" / "rehearsal.json")
    # revenu à l'identique de l'usine : la surcouche saute
    modes.apply_update(again, {"live_view": "pedalboard", "click_mode": "manual", "services": {"voice": True, "perfrec": True, "arrangement": False},
                               "inputs_off": [], "card": "", "band": "b_night"})
    again["ui"] = {"pages": ["live"], "boot": "live", "locked": False}      # apply garde ui.live : on remet la forme d'usine
    modes.commit(again)
    assert not os.path.exists(rack / "modes.local" / "rehearsal.json") and not _mode("rehearsal")["_modified"]


def test_le_battement_porte_la_feuille_entiere_les_vocabulaires_et_les_configs(rack):
    tbl = rigstatus.modes_table()
    r = next(m for m in tbl if m["id"] == "rehearsal")
    assert {"id", "label", "band", "perfrec", "take_kind"} <= set(r)                         # les clés d'avant
    assert r["services"]["voice"] is True and r["services"]["compo"] is True and r["live_view"] == "pedalboard"
    assert r["click_mode"] == "manual" and r["locked"] is False and r["factory"] is True and r["card"] is None
    g = next(m for m in tbl if m["id"] == "gig")
    assert g["locked"] is True and g["card"] == "hw:XR18"
    ctx = rigstatus.modes_ctx()
    assert set(ctx) == {"recorder", "click", "vocab", "spaces", "cards", "foot_lists", "modes_version"}   # + foot_lists (patch-as-preset §9 bis-9)
    assert "count_in" in ctx["recorder"] and "level" in ctx["click"]
    assert "perfrec" in ctx["vocab"]["services"] and ctx["vocab"]["live_views"]["timeline"] and "iem" in ctx["vocab"]["out_roles"]
    assert [s["id"] for s in ctx["spaces"]] == ["b_night", "b_earth"] and [c["id"] for c in ctx["cards"]] == ["V276", "XR18"]
    v1 = ctx["modes_version"]
    tones_jobs._mode_set({"mode": "rehearsal", "click_mode": "off"})
    assert rigstatus.modes_ctx()["modes_version"] != v1


def test_mode_set_refuse_tout_ou_rien_le_verrou_et_l_espace(rack):
    before = json.dumps(_mode("rehearsal"), sort_keys=True)
    with pytest.raises(RuntimeError) as ex:
        tones_jobs._mode_set({"mode": "rehearsal", "click_mode": "off", "card": "hw:Nope", "band": "b_mars", "locked": True, "foo": 1})
    msg = str(ex.value)
    assert msg.startswith("refused, nothing written") and "card: unknown card" in msg and "band: unknown space" in msg
    assert "locked: never set remotely" in msg and "foo: unknown field" in msg
    assert json.dumps(_mode("rehearsal"), sort_keys=True) == before                      # click_mode non écrit non plus
    for body in ({"mode": "rehearsal", "ui": {"locked": True}}, {"mode": "rehearsal", "perf_boost": True},
                 {"mode": "rehearsal", "perfrec_mode": "auto"}, {"mode": "nope", "name": "x"}):
        with pytest.raises(RuntimeError):
            tones_jobs._mode_set(body)
    # la règle d'espace : tenue si le job porte `space`
    with pytest.raises(RuntimeError, match="belongs to space b_night"):
        tones_jobs._mode_set({"mode": "rehearsal", "space": "b_earth", "name": "Répète"})
    with pytest.raises(RuntimeError, match="belongs to space none"):
        tones_jobs._mode_set({"mode": "gig", "space": "b_night", "name": "Concert"})
    # l'enveloppe commune des jobs (id, device, action, created_at) n'est jamais un champ du mode
    r = tones_jobs._mode_set({"id": 87, "device": "golem-df", "action": "mode-set", "created_at": "2026-09-26T20:00:00Z",
                              "mode": "rehearsal", "space": "b_night", "name": "Répète", "live_view": "timeline", "card": "XR18"})
    assert r["mode"]["name"] == "Répète" and r["mode"]["live_view"] == "timeline" and r["mode"]["card"] == "XR18"
    assert r["modes_version"] and any(m["id"] == "rehearsal" and m["label"] == "Répète" for m in r["modes"])


def test_mode_set_ne_touche_pas_au_mode_actif_pendant_une_prise_et_recorder_set_est_borne(rack):
    state.mode = {"id": "rehearsal", "ui": {}}
    state.perf = {"recording": True}
    with pytest.raises(RuntimeError, match="active mode and a take is recording"):
        tones_jobs._mode_set({"mode": "rehearsal", "name": "x"})
    state.perf = {"recording": False}
    state.mode = {"id": "gig", "ui": {"locked": True}}
    with pytest.raises(RuntimeError, match="locked"):
        tones_jobs._mode_set({"mode": "gig", "name": "x"})
    tones_jobs._mode_set({"mode": "rehearsal", "name": "ok"})                          # pas le mode actif : passe
    state.mode = {}
    with pytest.raises(RuntimeError, match="unknown field"):
        tones_jobs._recorder_set({"in1": True, "bogus": 1})
    with pytest.raises(RuntimeError, match="mode is one of"):
        tones_jobs._recorder_set({"mode": "stereo"})
    r = tones_jobs._recorder_set({"id": 89, "device": "golem-df", "action": "recorder-set", "created_at": "x",
                                  "in1": True, "in2": True, "mode": "tracks", "count_in": 5})
    assert r["recorder"]["in2"] is True and r["recorder"]["mode"] == "tracks" and r["recorder"]["count_in"] == 2
    state.perf = {"recording": True}
    with pytest.raises(RuntimeError, match="a take is recording"):
        tones_jobs._recorder_set({"in1": False})
