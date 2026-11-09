# SPDX-License-Identifier: GPL-3.0-or-later
"""Le lecteur d'accords des Standards (bridge/standards.py `parse_symbol`). Un symbole illisible est un accord qui NE
SONNE PAS en plein morceau. Le 2026-11-09, 21 grilles du corpus synchronisé avaient des accords muets : mineur-majeur 9
(`EmMaj9`), diminué-majeur 7 (`Ebdimmaj7`), ajout sur un autre noyau (`Bbmadd9`), quarte suspendue avec tierce
(`F#7sus4add3`). Comparé au lecteur d'avant sur les 1596 symboles du corpus : 13 changés, tous illisibles avant."""
import pytest

from bridge.standards import parse_symbol


@pytest.mark.parametrize("sym, ints", [
    ("EmMaj9", [0, 3, 7, 11, 14]),
    ("C#mMaj9", [0, 3, 7, 11, 14]),
    ("Ebdimmaj7", [0, 3, 6, 11]),
    ("Bbmadd9", [0, 3, 7, 14]),
    ("Cm7add11", [0, 3, 7, 10, 17]),
    ("F#7sus4add3", [0, 4, 5, 7, 10]),
])
def test_les_accords_qui_ne_sonnaient_pas(sym, ints):
    ch = parse_symbol(sym)
    assert ch is not None and ch["ints"] == ints


@pytest.mark.parametrize("sym, ints", [
    ("Cadd9", [0, 4, 7, 14]), ("Cm/maj7", [0, 3, 7, 11]), ("Am/maj7/G#", [0, 3, 7, 11]), ("C7sus", [0, 5, 7, 10]),
    ("Cdim7", [0, 3, 6, 9]), ("C#dim", [0, 3, 6]), ("Cmaj9", [0, 4, 7, 11, 14]), ("Bb7b9sus", [0, 5, 7, 10, 13]),
])
def test_ce_qui_se_lisait_deja_ne_change_pas(sym, ints):
    assert parse_symbol(sym)["ints"] == ints


@pytest.mark.parametrize("sym", ["Cfoo", "Cmaj7add", "H7", "Cadd"])
def test_un_reliquat_reste_illisible(sym):
    """Mieux vaut un None franc (dit par l'appelant) qu'un accord approximatif."""
    assert parse_symbol(sym) is None
