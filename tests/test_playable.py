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


def test_an_outboard_impulse_response_is_played_whole_by_ir_fx():
    assert PL.block_for("outboard", "ir") == "ir-fx"
    assert PL.plays({"gear": "outboard", "format": "ir"}) == ["ir-fx"]
    assert PL.plays({"gear": "outboard", "format": "nam"}) == ["preamp-nam", "comp-nam"]


def test_a_long_pedal_ir_is_an_effect_a_short_one_a_cab(tmp_path):
    import struct
    import wave

    def wav(name, ms):
        p = tmp_path / name
        with wave.open(str(p), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(48000)
            n = int(48 * ms)
            w.writeframes(b"".join(struct.pack("<h", int(20000 * (1 - i / n))) for i in range(n)))
        return str(p)
    assert PL.ir_kind_of([wav("cab.wav", 40)]) == "cab"
    assert PL.ir_kind_of([wav("cab.wav", 40), wav("spring.wav", 900)]) == "effect"
    assert PL.block_for("pedal", "ir", "effect") == "ir-fx" and PL.block_for("pedal", "ir", "cab") == "cab"


def test_a_block_quarantined_on_this_machine_plays_nothing(monkeypatch):
    monkeypatch.setattr(PL, "_quarantined", lambda: {"ir-fx": "no stereo convolver on Windows"})
    ok, why = PL.verdict("outboard", "ir")
    assert not ok and "no stereo convolver" in why


def test_unknown_gear_or_format_is_never_playable():
    assert PL.verdict("experimental", "nam")[0] is False
    assert PL.verdict("amp", "aidax")[0] is False
    assert PL.verdict("", "nam")[0] is False


def test_a_multi_gear_pack_is_playable_when_one_of_its_gears_is():
    assert PL.block_for("amp,cab", "ir") == "cab"


def test_a_tab_searches_only_the_formats_it_can_install():
    assert PL.formats_for("outboard") is None                  # NAM (préampli) ET IR (ir-fx) y jouent
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
    monkeypatch.setattr(R, "_verdict", lambda g, f: {"playable": f != "ir", "why": ""})   # une machine sans ir-fx
    out = R.search_tones("", "outboard")
    assert "format=" not in seen["path"]                        # NAM et IR y jouent : pas de filtre
    assert [(t["format"], t["count"], t["playable"]) for t in out] == [("nam", 12, True), ("ir", 13, False)]
    R.search_tones("", "outboard", fmt="ir")
    assert "format=ir" in seen["path"]


def test_the_catalog_marks_a_pack_golem_cannot_play(monkeypatch, tmp_path):
    import json
    from bridge import routes_content as RC, config as C
    p = tmp_path / "tones-index.json"
    from bridge import playable
    monkeypatch.setattr(playable, "_quarantined", lambda: {"ir-fx": "not here"})
    p.write_text(json.dumps({"tones": [
        {"id": 1, "gear": "outboard", "format": "ir", "models": []},
        {"id": 2, "gear": "outboard", "format": "nam", "models": []}]}))
    monkeypatch.setattr(C, "CATALOG", str(p))
    tones = {t["id"]: t for t in RC.get_catalog()["tones"]}
    assert tones[1]["playable"] is False and tones[1]["why"]
    assert "playable" not in tones[2]


def test_ir_fx_writes_its_dry_and_wet_even_when_the_patch_names_neither():
    # le 2026-11-14 : écoute du RE-301 depuis la Library, bloc posé sans potards -> le convolveur gardait SES défauts
    # (direct à -60 dB) : la guitare disparaissait derrière l'IR. Les défauts du catalogue s'écrivent à la compile.
    from bridge import compile_rig as CR
    CR._FX_DEFS = None
    blocks = [{"id": "ir-fx", "type": "ir-fx", "params": {}}]
    CR._fill_compile_defaults(blocks)
    assert blocks[0]["params"] == {"dry": 0, "wet": -6}
