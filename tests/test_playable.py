# SPDX-License-Identifier: GPL-3.0-or-later
"""Ce que golem sait jouer (bridge/playable.py, docs/library-tones.md §7) — le RE-301 du 2026-11-14."""
from bridge import playable as PL


def test_each_nam_capture_has_its_block():
    assert PL.block_for("amp", "nam") == "amp-nam"
    assert PL.block_for("amp-cab", "nam") == "amp"
    assert PL.block_for("pedal", "nam") == "pedal-nam"
    assert PL.block_for("outboard", "nam") == "preamp-nam"


def test_a_cab_like_impulse_response_is_played_by_the_cab_block():
    for g in ("cab", "pedal", "amp", "amp-cab"):
        assert PL.block_for(g, "ir") == "cab", g


def test_an_outboard_impulse_response_is_refused_with_a_sentence():
    ok, why = PL.verdict("outboard", "ir")
    assert not ok and "full-length impulse response" in why


def test_unknown_gear_or_format_is_never_playable():
    assert PL.verdict("experimental", "nam")[0] is False
    assert PL.verdict("amp", "aidax")[0] is False
    assert PL.verdict("", "nam")[0] is False


def test_a_multi_gear_pack_is_playable_when_one_of_its_gears_is():
    assert PL.block_for("amp,cab", "ir") == "cab"


def test_a_tab_searches_only_the_formats_it_can_install():
    assert PL.formats_for("outboard") == "nam"
    assert PL.formats_for("cab") == "ir"
    assert PL.formats_for("amp_amp-cab") is None               # les deux formats y jouent
    assert PL.formats_for("") is None


def test_search_results_carry_format_and_verdict(monkeypatch):
    from bridge import routes_t3k as R
    seen = {}

    def fake_get(path):
        seen["path"] = path
        return 200, {"data": [
            {"id": 1, "title": "BAE 1073MP", "gear": "outboard", "format": "nam", "models_count": 12},
            {"id": 2, "title": "Roland Re-301", "gear": "outboard", "format": "ir", "irs_count": 13}]}
    monkeypatch.setattr(R._t3k, "api_get", fake_get)
    monkeypatch.setattr(R, "_installed_ids", lambda: set())
    out = R.search_tones("", "outboard")
    assert "format=nam" in seen["path"]                         # l'onglet Outboard ne cherche que du NAM
    assert [(t["format"], t["count"], t["playable"]) for t in out] == [("nam", 12, True), ("ir", 13, False)]
    R.search_tones("", "outboard", fmt="ir")
    assert "format=ir" in seen["path"]


def test_the_catalog_marks_a_pack_golem_cannot_play(monkeypatch, tmp_path):
    import json
    from bridge import routes_content as RC, config as C
    p = tmp_path / "tones-index.json"
    p.write_text(json.dumps({"tones": [
        {"id": 1, "gear": "outboard", "format": "ir", "models": []},
        {"id": 2, "gear": "outboard", "format": "nam", "models": []}]}))
    monkeypatch.setattr(C, "CATALOG", str(p))
    tones = {t["id"]: t for t in RC.get_catalog()["tones"]}
    assert tones[1]["playable"] is False and tones[1]["why"]
    assert "playable" not in tones[2]
