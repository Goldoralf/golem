# SPDX-License-Identifier: GPL-3.0-or-later
"""La pompe manouche (docs/standards.md §10) : formes, accent, étalement, styles, décompte.
Éprouvée sur le standard d'usine Crooked Lantern (library/factory/standards), pas sur ce que le rack a installé."""
import os
import shutil

import pytest

from bridge import config, standards as S

MANOUCHE = {"keys": False, "bass": True, "drums": False, "guitar": True}


@pytest.fixture
def g(tmp_path, monkeypatch):
    std = tmp_path / "standards"
    os.makedirs(std / "golem")
    shutil.copy(os.path.join(config.ROOT, "library", "factory", "standards", "crooked-lantern.golem"), std / "golem")
    monkeypatch.setattr(S, "STD_DIR", str(std))
    monkeypatch.setattr(S, "SYNCED_DIR", str(std / "synced"))
    monkeypatch.setattr(S, "GOLEM_DIR", str(std / "golem"))
    S._cache.update(sig=None)
    yield S.get_grid("crooked-lantern")
    S._cache.update(sig=None)


def _guitar(r):
    return [e for e in r["events"] if e[3] == S.LANE_GUITAR and e[2]]


def test_shapes_are_guitar_shapes():
    assert S.pompe_shape(S.parse_symbol("Dm6")) == [50, 59, 65, 69]         # x5x465
    assert S.pompe_shape(S.parse_symbol("A7")) == [45, 55, 61]              # pas de quinte
    # maj7 -> 6 : la septième majeure n'est pas du langage manouche
    bb = S.pompe_shape(S.parse_symbol("Bbmaj7"))
    assert {n % 12 for n in bb} == {10, 7, 2, 5} and bb[0] % 12 == 10
    # 7b9 -> dim7 posé sur la b9
    assert {n % 12 for n in S.pompe_shape(S.parse_symbol("A7b9"))} == {10, 1, 4, 7}
    # la fondamentale jouée sur les cordes graves
    for sym in ("Dm6", "Gm7", "C6", "Em7b5", "F#dim7", "Bb7"):
        assert 40 <= S.pompe_shape(S.parse_symbol(sym))[0] <= 51


def test_pompe_accent_and_length_on_2_and_4(g):
    r = S.render(g, parts=MANOUCHE, bpm=200)
    ev = [e for e in r["events"] if e[3] == S.LANE_GUITAR]
    ons = [e for e in ev if e[2]]
    bar = r["bar_ppq"]
    downs = [e for e in ons if (e[0] % bar) < 200]                         # temps 1 (étalé)
    twos = [e for e in ons if S.PPQ <= (e[0] % bar) < S.PPQ + 200]         # temps 2
    assert downs and twos
    assert max(e[2] for e in downs) < min(e[2] for e in twos)              # 2 accentué
    # étalement : les cordes d'un même coup ne partent pas ensemble
    first = sorted(e[0] for e in ons if e[0] < S.PPQ // 2)
    assert len(set(first)) == len(first) > 1


def test_without_guitar_render_is_unchanged(g):
    a = S.render(g, parts={"keys": True, "bass": True})
    b = S.render(g, parts={"keys": True, "bass": True, "guitar": False}, pompe="bossa")
    assert a["events"] == b["events"]
    assert not _guitar(a)


def test_styles_differ_and_auto_follows_tune(g):
    seen = {}
    for st in S.POMPE_STYLES:
        seen[st] = tuple(_guitar(S.render(g, parts=MANOUCHE, bpm=200, pompe=st)))
        assert seen[st], st
    assert len(set(seen.values())) == len(S.POMPE_STYLES)
    assert S.render(g, parts=MANOUCHE, bpm=200, pompe="auto")["events"] == \
        S.render(g, parts=MANOUCHE, bpm=200, pompe="pompe")["events"]
    assert S.pompe_style("swing", 3, 120) == "valse"
    assert S.pompe_style("swing", 4, 260) == "pompe-fast"
    assert S.pompe_style("bossa", 4, 120) == "bossa"


def test_manouche_bass_plays_two_and_count_in_on_guitar(g):
    r = S.render(g, parts=MANOUCHE, bpm=200, count_in=1)
    bass = [e for e in r["events"] if e[3] == 1 and e[2]]
    assert all((e[0] - r["count_in_ppq"]) % (2 * S.PPQ) == 0 for e in bass)   # 1 et 3
    cin = [e for e in r["events"] if e[0] < r["count_in_ppq"] and e[2]]
    assert cin and all(e[3] == S.LANE_GUITAR and e[1] <= 86 for e in cin)


def test_note_offs_close_every_guitar_note(g):
    for st in S.POMPE_STYLES:
        r = S.render(g, parts=MANOUCHE, bpm=200, pompe=st, choruses=2)
        on = {}
        for at, n, v, lane in r["events"]:
            assert at < r["len_ppq"]
            if lane == S.LANE_GUITAR:
                on[n] = on.get(n, 0) + (1 if v else -1)
        assert all(x == 0 for x in on.values()), st


def test_crooked_lantern_is_a_manouche_chart(g):
    assert g and g["rhythm"] == "manouche"
    assert (g.get("play") or {}).get("parts") == MANOUCHE
