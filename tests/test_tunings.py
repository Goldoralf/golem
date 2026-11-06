# SPDX-License-Identifier: GPL-3.0-or-later
"""Accordages (2026-10-08) : la table copiée de golem.fm, filtrée par rôle, et l'accordeur qui lit le bloc Tuner."""
from bridge import tunings as T, store


def test_table_copiee_de_golem_fm():
    d = T.load()
    ids = [t["id"] for t in d["tunings"]]
    assert len(ids) == 20 and len(set(ids)) == 20
    for t in d["tunings"]:
        assert t["midi"] == sorted(t["midi"]) and len(t["midi"]) == len(t["notes"])
    assert T.resolve("6-std", "guitar")["midi"] == [40, 45, 50, 55, 59, 64]      # E2 A2 D3 G3 B3 E4


def test_la_liste_suit_le_role():
    assert {t["family"] for t in T.for_role("guitar")} == {"6-string", "7-string", "8-string"}
    assert {t["family"] for t in T.for_role("bass")} == {"bass-4", "bass-5"}
    assert T.resolve("", "bass")["id"] == "bass-4-std"            # vide = défaut du rôle
    assert T.resolve("7-std", "bass")["id"] == "bass-4-std"       # une basse ne prend pas un 7 cordes
    assert len(T.resolve("8-std", "guitar")["midi"]) == 8


def test_l_accordeur_lit_le_bloc_tuner():
    """La forme de Paper Kite (le bloc Tuner dans guitar 1, IN 2 ; la voix en IN 1) : l'accordage posé sur le bloc
    voyage jusqu'à l'accordeur ; sans accordage, "" (le défaut du rôle)."""
    def preset(tuner_params):
        return {"id": "t", "lanes_v": 2, "scenes": [{"id": "A"}], "lanes": [
            {"id": "voice-1", "key": "voice-1", "role": "voice", "input": 1, "in_sel": "1", "chain": {"pre": [], "post": []}},
            {"id": "guitar-1", "key": "guitar-1", "role": "guitar", "input": 2, "in_sel": "2",
             "chain": {"pre": ([{"type": "tuner", "id": "tuner-x", "params": tuner_params, "foot": 10}] if tuner_params is not None else []),
                       "post": []}}]}
    # l'ENTRÉE physique dépend de la carte de la machine (résolue par nom) : on ne teste que rôle et accordage
    assert store.tuner_source(preset({}))[1:] == ("guitar", "")
    assert store.tuner_source(preset({"tuning": "7-std"}))[1:] == ("guitar", "7-std")
    assert store.tuner_source(preset(None))[2] == ""


def test_sans_bloc_tuner_l_accordeur_ecoute_la_lane_a_cordes_pas_l_entree_1(monkeypatch):
    """Voix sur IN 1, guitare sur IN 2, aucun bloc Tuner : l'accordeur écoutait le micro (2026-10-15)."""
    lanes = [{"key": "voice-1", "input": 1, "role": "voice"}, {"key": "guitar-1", "input": 2, "role": "guitar"}]
    monkeypatch.setattr(store, "lanes_of", lambda p: lanes)
    assert store.tuner_source({"id": "x"}) == (2, "guitar", "")
