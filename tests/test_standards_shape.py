# SPDX-License-Identifier: GPL-3.0-or-later
"""La carte de standard (golem.fm StandardCard, 2026-10-17) : la FORME (lettres des sections dans l'ordre joué) et
l'APERÇU (accords par mesure des 32 premières), calculés par le bridge — la page n'a plus de requête par carte."""
from bridge import standards as S


def _bar(*syms):
    return [{"sym": s, "len": 4.0 / len(syms), "beat": 1.0 + i} for i, s in enumerate(syms)]


def test_forme_et_apercu():
    g = {"sections": [{"id": "A1", "label": "A", "bars": [_bar("Cm7"), _bar("Dm7b5", "G7")]},
                      {"id": "B3", "label": "B", "bars": [_bar("Eb7"), [{"sym": None}]]}],
         "order": ["A1", "A1", "B3", "A1"]}
    form, shape = S._shape(g)
    assert form == "AABA"
    assert shape == [1, 2, 1, 2, 1, 0, 1, 2]


def test_l_apercu_s_arrete_a_32_mesures():
    g = {"sections": [{"id": "A", "label": "A", "bars": [_bar("C")] * 20}], "order": ["A", "A"]}
    form, shape = S._shape(g)
    assert form == "AA" and len(shape) == S.SHAPE_BARS


def test_la_liste_porte_forme_et_apercu():
    for m in S.list_standards()[:5]:
        assert isinstance(m["form"], str) and isinstance(m["shape"], list) and len(m["shape"]) <= S.SHAPE_BARS
