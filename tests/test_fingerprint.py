# SPDX-License-Identifier: GPL-3.0-or-later
"""Comparer deux empreintes Chromaprint (golem-format.md §12.5) : décodage exact, et le seuil tient sur de vraies
empreintes (tests/data/fingerprints.json — produites par libchromaprint le 2026-10-08)."""
import json
import os

import pytest

from bridge import fingerprint as F

D = json.load(open(os.path.join(os.path.dirname(__file__), "data", "fingerprints.json")))


def test_le_decodage_rend_exactement_les_entiers_de_libchromaprint():
    algo, raw = F.decode(D["kite"])
    assert algo == 1 and raw == D["_raw_kite"]          # TEST2 = 1 dans l'enum de libchromaprint (le « 2 » de fpcalc)


@pytest.mark.parametrize("k", ["reencode96k", "delay70ms", "delay300ms", "cut20ms", "cut60ms", "cut90ms", "cut500ms", "cut1s"])
def test_le_meme_enregistrement_est_reconnu(k):
    ok, r = F.same_recording(D["kite"], D[k])
    assert ok, (k, r)


@pytest.mark.parametrize("k", ["other_song", "other_song_mix", "same_song_bass_stem", "same_song_drums_stem"])
def test_un_autre_enregistrement_ne_l_est_pas(k):
    ok, r = F.same_recording(D["kite"], D[k])
    assert not ok, (k, r)


def test_la_duree_tranche_d_abord_et_une_chaine_cassee_ne_ressemble_a_rien():
    assert F.same_recording(D["kite"], D["reencode96k"], 297893, 300500) == (False, None)   # 2,6 s d'écart
    assert F.same_recording(D["kite"], D["reencode96k"], 297893, 299000)[0]                  # 1,1 s : on compare
    assert F.same_recording(D["kite"], "AQAA-not-really") == (False, None)
