# SPDX-License-Identifier: GPL-3.0-or-later
"""docs/bars-format.md (FIGÉ 2026-10-07) : la carte des mesures d'une backing — validation stricte, instants
réels, et parties de l'arrangement calées dessus."""
import json

import pytest

from bridge import arrangement as A
from bridge import bars as B


def _doc(**kw):
    d = {"version": 1, "slug": "s", "rev": "r1", "source": "aligned", "end_ms": 9000,
         "bars": [{"bar": 1, "ms": 290, "num": 4, "den": 4, "confirmed": True, "beats": [290, 980, 1665, 2350], "beats_source": "detected"},
                  {"bar": 2, "ms": 3017, "num": 2, "den": 4, "confirmed": True},
                  {"bar": 3, "ms": 4449, "num": 4, "den": 4, "confirmed": False, "beats": [4449, 5170, 5890, 6610], "beats_source": "interpolated"}]}
    d.update(kw)
    return d


def test_une_carte_conforme_passe():
    doc, why = B.validate(_doc(), "s")
    assert why is None and doc


@pytest.mark.parametrize("bad, mot", [
    ({"version": 2}, "version"), ({"slug": "x"}, "slug"), ({"bars": []}, "no bars"),
    ({"end_ms": 4000}, "end_ms"),
])
def test_une_carte_invalide_est_rejetee_en_entier(bad, mot):
    doc, why = B.validate(_doc(**bad), "s")
    assert doc is None and mot in why


def test_mesures_non_contigues_ou_temps_qui_debordent():
    d = _doc(); d["bars"][1]["bar"] = 3
    assert B.validate(d, "s")[0] is None
    d = _doc(); d["bars"][0]["beats"] = [290, 980, 1665, 3100]        # dernier temps après la mesure 2
    assert B.validate(d, "s")[0] is None


def test_instants_reels_et_extrapolation():
    doc = _doc()
    assert B.time_of(doc, 1) == 0.29 and B.time_of(doc, 1, 2) == 0.98
    assert B.time_of(doc, 2, 2) == pytest.approx(3.017 + (4.449 - 3.017) / 2)   # sans beats : régulier
    assert B.time_of(doc, 4) == pytest.approx(9.0)                               # fin de la carte = end_ms
    assert B.time_of(doc, 5) == pytest.approx(9.0 + (9.0 - 4.449))               # au-delà : dernière mesure


def test_les_temps_du_click_et_les_stats():
    doc = _doc()
    t = B.ticks(doc)
    assert t[:4] == [(290, 1), (980, 0), (1665, 0), (2350, 0)] and t[4] == (3017, 1) and len(t) == 10
    st = B.stats(doc)
    assert st["bars"] == 3 and st["confirmed"] == 2 and st["approx_beats"] == 2 and st["beats"] is False


def test_les_parties_tombent_sur_les_mesures_reelles():
    """Paper Kite : la partie qui commence à la mesure 3 part à 4,449 s, pas à 4,14 s (tempo de la fiche)."""
    p = {"id": "p", "bpm": 87, "scenes": [{"id": "A"}, {"id": "B"}],
         "config": {"arr": {"blocks": [{"type": "arrangement", "id": "a", "params": {"sections": [
             {"name": "drum", "bars": 1, "scene": "A"}, {"name": "drum 2/4", "bars": 1, "sig": {"num": 2, "den": 4}},
             {"name": "intro", "bars": 1, "scene": "B"}]}}]}}}
    sans = A.plan(p)
    avec = A.plan(p, _doc())
    assert sans[2]["at"] == pytest.approx(4.138, abs=0.01)
    assert [round(x["at"], 3) for x in avec] == [0.29, 3.017, 4.449]
    assert avec[2]["dur"] == pytest.approx(9.0 - 4.449)


def test_dans_un_golem_la_carte_peut_ne_pas_porter_de_slug(monkeypatch):
    """song-sharing.md §2.8 : le filtre de sortie retire le slug de sync/bars.json. Rangée dans un .golem (clé = id de
    chanson), une carte sans slug passe ; un slug FAUX reste refusé ; un cache (clé = slug) reste strict."""
    from bridge import golemfm as M
    monkeypatch.setattr(M, "golemfm_slug", lambda key: "s")
    d = _doc(); del d["slug"]
    assert B.validate(d, "ct:abc")[1] is None
    assert "slug" in B.validate(_doc(slug="x"), "ct:abc")[1]
    assert "slug" in B.validate(d, "s")[1]
