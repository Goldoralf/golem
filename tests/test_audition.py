# SPDX-License-Identifier: GPL-3.0-or-later
"""Écouter une capture depuis la Library (bridge/audition.py, docs/library-tones.md §4)."""
import copy

import pytest

from bridge import audition as A


def _preset():
    return {"id": "p1", "name": "Test", "lanes": [
        {"id": "guitar-1", "role": "guitar", "in_role": "guitar", "states": [{"id": "st-A", "blocks": {"ts": False}}],
         "chain": {"pre": [{"id": "gate", "type": "gate", "params": {}},
                           {"id": "ts", "type": "pedal-nam", "ref": "1", "model": "11", "params": {"input": 0, "output": -3}}],
                   "split": {"mode": "merge", "branches": [
                       {"id": "a", "blocks": [{"id": "head", "type": "amp-nam", "ref": "2", "model": "21", "params": {"output": -2}},
                                              {"id": "v30", "type": "cab", "ref": "3", "model": "31", "params": {"level": 0}}]},
                       {"id": "b", "blocks": [{"id": "jc", "type": "amp", "ref": "4", "model": "41", "params": {}}]}]},
                   "post": [{"id": "verb", "type": "reverb", "params": {}}]}},
        {"id": "bass-1", "role": "bass", "in_role": "bass", "states": [], "chain": {"pre": [], "post": []}}],
        "scenes": [{"id": "A", "blocks": {"ts": False}, "branches": {"a": {"mute": True}}, "lanes": {"guitar-1": {"state": "st-A"}}},
                   {"id": "B", "blocks": {}, "branches": {}, "lanes": {}}]}


def _tone(gear, tid="99", name="Test Amp", models=("991", "992"), **kw):
    return {"id": tid, "gear": gear, "amp": name, "models": [{"id": m, "name": m} for m in models], **kw}


def _blocks(doc, lane="guitar-1"):
    L = next(x for x in doc["lanes"] if x["id"] == lane)
    ch = L["chain"]
    out = list(ch["pre"])
    for br in (ch.get("split") or {}).get("branches") or []:
        out += br["blocks"]
    return out + ch["post"]


def test_the_original_preset_is_never_touched():
    p = _preset()
    before = copy.deepcopy(p)
    doc, _ = A.build(p, "A", _tone("amp-cab"))
    assert p == before
    assert doc["id"] == A.AUDITION_ID


def test_a_head_and_cab_capture_swaps_the_amp_of_the_branch_the_scene_plays():
    # scène A : la branche « a » est muette -> c'est l'ampli de « b » (jc) qui joue, donc qui change
    doc, info = A.build(_preset(), "A", _tone("amp-cab", models=("991",)))
    jc = next(b for b in _blocks(doc) if b["id"] == "jc")
    assert (jc["type"], jc["ref"], jc["model"]) == ("amp", "99", "991")
    assert info["block"] == "jc"
    # scène B : la branche « a » joue
    doc, info = A.build(_preset(), "B", _tone("amp-cab"))
    head = next(b for b in _blocks(doc) if b["id"] == "head")
    assert head["type"] == "amp" and head["params"] == {"output": -2}
    assert doc["scenes"][1]["blocks"]["v30"] is False          # le baffle est dans la capture : pas de deuxième


def test_a_head_only_capture_keeps_the_cab_and_says_when_there_is_none():
    doc, info = A.build(_preset(), "B", _tone("amp"))
    assert next(b for b in _blocks(doc) if b["id"] == "head")["type"] == "amp-nam"
    assert info["notes"] == []
    doc, info = A.build(_preset(), "A", _tone("amp"))           # branche b : jc, sans baffle
    assert info["notes"] == ["no_cab"]


def test_the_chosen_model_is_used_and_an_unknown_one_refused():
    doc, info = A.build(_preset(), "B", _tone("amp"), "992")
    assert info["model"] == "992"
    with pytest.raises(A.AuditionError):
        A.build(_preset(), "B", _tone("amp"), "nope")


def test_a_pedal_capture_is_switched_on_in_the_current_scene():
    doc, info = A.build(_preset(), "A", _tone("pedal", name="Klon"))
    assert info["block"] == "ts"
    assert doc["scenes"][0]["blocks"]["ts"] is True
    assert doc["lanes"][0]["states"][0]["blocks"]["ts"] is True


def test_a_pedal_goes_in_front_of_the_amp_when_the_lane_has_none():
    p = _preset()
    p["lanes"][0]["chain"]["pre"] = [{"id": "gate", "type": "gate", "params": {}}]
    p["lanes"][0]["chain"]["split"]["branches"][0]["blocks"].insert(0, {"id": "x", "type": "gate", "params": {}})
    doc, info = A.build(p, "B", _tone("pedal"))
    br = doc["lanes"][0]["chain"]["split"]["branches"][0]["blocks"]
    assert [b["type"] for b in br][:3] == ["gate", "pedal-nam", "amp-nam"]


def test_a_cab_replaces_the_cab_or_lands_after_the_amp():
    doc, info = A.build(_preset(), "B", _tone("cab", name="Palmer 2x12"))
    assert info["block"] == "v30"
    doc, info = A.build(_preset(), "A", _tone("cab"))           # branche b : un `amp` (tête + baffle), pas de cab
    br = doc["lanes"][0]["chain"]["split"]["branches"][1]["blocks"]
    assert [b["type"] for b in br] == ["amp", "cab"] and info["notes"] == ["amp_has_cab"]


def test_outboard_is_a_compressor_or_a_preamp_by_its_name():
    assert A.outboard_type({"amp": "UREI/Universal Audio 1176"}) == "comp-nam"
    assert A.outboard_type({"amp": "BAE 1073"}) == "preamp-nam"
    doc, info = A.build(_preset(), "B", _tone("outboard", name="UREI 1176"))
    assert doc["lanes"][0]["chain"]["pre"][0]["type"] == "comp-nam"
    doc, info = A.build(_preset(), "B", _tone("outboard", name="BAE 1073"))
    br = doc["lanes"][0]["chain"]["split"]["branches"][0]["blocks"]
    assert [b["type"] for b in br][:2] == ["preamp-nam", "amp-nam"]


def test_a_bass_capture_is_heard_on_the_bass_lane():
    p = _preset()
    p["lanes"][1]["chain"]["pre"] = [{"id": "svt", "type": "amp", "ref": "5", "model": "51", "params": {}}]
    doc, info = A.build(p, "B", _tone("amp-cab", name="Ampeg SVT", tags=["bass"]))
    assert info["lane"] == "bass-1"


def test_no_patch_or_no_lane_is_said_in_plain_words():
    with pytest.raises(A.AuditionError, match="Load a patch first"):
        A.build(None, None, _tone("amp"))
    p = _preset()
    p["lanes"] = [p["lanes"][1]]
    with pytest.raises(A.AuditionError, match="no guitar lane"):
        A.build(p, "A", _tone("amp"))
