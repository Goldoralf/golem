# SPDX-License-Identifier: GPL-3.0-or-later
"""La main par formes (bridge/fingering.py, docs/tablature-fingering.md §5) : jouable, continue, et pas naïve."""
from bridge import fingering as FG

GTR = FG.STANDARD["guitar"]


def _ok(placed, tuning=GTR):
    """Chaque note est sur une corde qui la donne, une seule note par corde."""
    n = len(tuning)
    strings = [s for _, s, _ in placed]
    return (len(set(strings)) == len(strings)
            and all(s is not None and tuning[n - s] + f == p for p, s, f in placed))


def test_chaque_candidat_est_jouable_et_tient_dans_la_main():
    w = FG.WEIGHTS["guitar"]
    cs = FG.candidates([48, 55, 60, 64], GTR, w)                   # do majeur
    assert cs and all(_ok(c) for c in cs)
    for c in cs:
        fr = [f for _, _, f in c if f > 0]
        assert not fr or max(fr) - min(fr) <= w["max_span"]


def test_une_gamme_ne_saute_pas_a_l_autre_bout_du_manche():
    # la mineur sur deux octaves : avant la portée de la main (`reach`), la fin de la gamme sautait en case 12-14.
    # Une gamme glisse de position en position ; elle ne saute pas de 9 cases.
    line = [[p] for p in (45, 48, 50, 52, 55, 57, 60, 62, 64, 67, 69, 72)]
    out = FG.fingering(line, tuning=GTR)
    frets = [g[0][2] for g in out]
    assert all(_ok(g) for g in out)
    assert max(abs(b - a) for a, b in zip(frets, frets[1:]) if a and b) <= 4
    assert max(frets) <= 10


def test_un_power_chord_est_une_forme():
    out = FG.fingering([[45, 52, 57]] * 4 + [[47, 54, 59]] * 4, tuning=GTR)
    assert out[0] == [(57, 4, 7), (52, 5, 7), (45, 6, 5)] or out[0] == [(57, 3, 2), (52, 4, 2), (45, 5, 0)]
    assert all(_ok(g) for g in out)


def test_une_note_injouable_est_dite_pas_inventee():
    out = FG.fingering([[30, 52]], tuning=GTR)                     # 30 est sous le mi grave
    assert (30, None, None) in out[0] and _ok([x for x in out[0] if x[1] is not None])


def test_la_basse_a_sa_main():
    out = FG.fingering([[28], [33], [38], [43], [45]], instrument="bass")
    assert all(_ok(g, FG.STANDARD["bass"]) for g in out)


def test_un_groupe_vide_ne_casse_rien():
    assert FG.fingering([], tuning=GTR) == []
    assert FG.fingering([[]], tuning=GTR) == [[]]


def test_la_pompe_manouche_prend_ses_formes_en_enchainement():
    # Dm6 · Gm6 · A7 · Dm6 (Crooked Lantern) : les formes de la grille, x5x465 · 3x233x · 5x56xx
    out = FG.fingering([[50, 59, 65, 69], [43, 52, 58, 62], [45, 55, 61], [50, 59, 65, 69]], tuning=GTR)
    shape = [sorted((s, f) for _, s, f in g) for g in out]
    assert shape[0] == [(1, 5), (2, 6), (3, 4), (5, 5)]
    assert shape[1] == [(2, 3), (3, 3), (4, 2), (6, 3)]
    assert shape[2] == [(3, 6), (4, 5), (6, 5)]
